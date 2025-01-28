import copy
import importlib
from typing import Dict, Union

import pandas as pd
from pandas import DataFrame
from pydantic import BaseModel

from mindsdb.integrations.libs.base import BaseMLEngine
from mindsdb.utilities import log
from langchain_core.embeddings import Embeddings
from mindsdb.integrations.handlers.langchain_embedding_handler.vllm_embeddings import VLLMEmbeddings
from mindsdb.integrations.handlers.langchain_embedding_handler.fastapi_embeddings import FastAPIEmbeddings

logger = log.getLogger(__name__)

# construct the embedding model name to the class mapping
# we try to import all embedding models from langchain_community.embeddings
# for each class, we get a more user friendly name for it
# E.g. OpenAIEmbeddings -> OpenAI
# This is used for the user to select the embedding model
EMBEDDING_MODELS = {
    'VLLM': 'VLLMEmbeddings',
    'vllm': 'VLLMEmbeddings',
    'FastAPI': 'FastAPIEmbeddings',
    'fastapi': 'FastAPIEmbeddings'

}

try:
    module = importlib.import_module("langchain_community.embeddings")
    # iterate __all__ to get all the classes
    for class_name in module.__all__:
        class_ = getattr(module, class_name)
        if not issubclass(class_, Embeddings):
            continue
        # convert the class name to a more user friendly name
        # e.g. OpenAIEmbeddings -> OpenAI
        user_friendly_name = class_name.replace("Embeddings", "")
        EMBEDDING_MODELS[user_friendly_name] = class_name
        EMBEDDING_MODELS[user_friendly_name.lower()] = class_name

except ImportError:
    raise Exception(
        "The langchain is not installed. Please install it with `pip install langchain-community`."
    )


def get_langchain_class(class_name: str) -> Embeddings:
    """Returns the class object of the handler class.

    Args:
        class_name (str): Name of the class

    Returns:
        langchain.embeddings.BaseEmbedding: The class object
    """
    # First check if it's our custom VLLMEmbeddings
    if class_name == "VLLMEmbeddings":
        return VLLMEmbeddings

    if class_name == "FastAPIEmbeddings":
        return FastAPIEmbeddings

    # Then try langchain_community.embeddings
    try:
        module = importlib.import_module("langchain_community.embeddings")
        class_ = getattr(module, class_name)
    except ImportError:
        raise Exception(
            "The langchain is not installed. Please install it with `pip install langchain`."
        )
    except AttributeError:
        raise Exception(
            f"Could not find the class {class_name} in langchain_community.embeddings. Please check the class name."
        )
    return class_


def construct_model_from_args(args: Dict) -> Embeddings:
    """
    Deserializes the model from the model storage
    """
    target = args.pop("target", None)
    class_name = args.pop("class", LangchainEmbeddingHandler.DEFAULT_EMBEDDING_CLASS)
    if class_name in EMBEDDING_MODELS:
        logger.info(
            f"Mapping the user friendly name {class_name} to the class name: {EMBEDDING_MODELS[class_name]}"
        )
        class_name = EMBEDDING_MODELS[class_name]
    MODEL_CLASS = get_langchain_class(class_name)
    serialized_dict = copy.deepcopy(args)

    # Make sure we don't pass in unnecessary arguments.
    if issubclass(MODEL_CLASS, BaseModel):
        serialized_dict = {
            k: v for k, v in serialized_dict.items() if k in MODEL_CLASS.model_fields
        }

    model = MODEL_CLASS(**serialized_dict)
    if target is not None:
        args["target"] = target
    args["class"] = class_name
    return model


class LangchainEmbeddingHandler(BaseMLEngine):
    """
    Bridge class to connect langchain.embeddings module to mindsDB
    """

    DEFAULT_EMBEDDING_CLASS = "OpenAIEmbeddings"

    def __init__(self, model_storage, engine_storage, **kwargs) -> None:
        super().__init__(model_storage, engine_storage, **kwargs)
        self.generative = True

    def create(
        self,
        target: str,
        df: Union[DataFrame, None] = None,
        args: Union[Dict, None] = None,
    ) -> None:
        # get the class name from the args
        user_args = args.get("using", {})

        # infer the input columns arg if user did not provide it
        # from the columns of the input dataframe if it is provided
        if "input_columns" not in user_args and df is not None:
            # ignore private columns starts with __mindsdb
            # ignore target column in the input dataframe
            user_args["input_columns"] = [
                col
                for col in df.columns.tolist()
                if not col.startswith("__mindsdb") and col != target
            ]
            # unquote the column names -- removing surrounding `
            user_args["input_columns"] = [
                col.strip("`") for col in user_args["input_columns"]
            ]

        elif "input_columns" not in user_args:
            # set as empty list if the input_columns is not provided
            user_args["input_columns"] = []

        # this may raise an exception if
        # the arguments are not sufficient to create such as class
        # due to e.g., lack of API key
        # But the validation logic is handled by langchain and pydantic
        construct_model_from_args(user_args)

        # save the model to the model storage
        target = target or "embeddings"
        user_args[
            "target"
        ] = target  # this is the name of the column to store the embeddings
        self.model_storage.json_set("args", user_args)

    def predict(self, df: DataFrame, args) -> DataFrame:
        # reconstruct the model from the model storage
        user_args = self.model_storage.json_get("args")
        model = construct_model_from_args(user_args)

        # get the target from the model storage
        target = user_args["target"]
        # run the actual embedding vector generation
        # TODO: need a better way to handle this
        # unquote the column names -- removing surrounding `
        cols_dfs = [col.strip("`") for col in df.columns.tolist()]
        df.columns = cols_dfs

        # if input_columns is an empty list, use all the columns
        input_columns = user_args.get("input_columns") or df.columns.tolist()

        # check all the input columns are in the df
        # ignore surrounding ` in the column names when checking
        if not all([col in cols_dfs for col in input_columns]):
            raise Exception(
                f"Input columns {input_columns} not found in the input dataframe. Available columns are {df.columns}"
            )

        # Get batch size from model or use default
        batch_size = getattr(model, 'batch_size', 32)
        logger.info(f"Processing embeddings with batch size: {batch_size}")

        # Process in batches to avoid memory issues
        all_embeddings = []
        total_rows = len(df)
        logger.info(f"Starting batch processing for {total_rows} documents")

        for start_idx in range(0, total_rows, batch_size):
            end_idx = min(start_idx + batch_size, total_rows)
            batch_df = df.iloc[start_idx:end_idx]
            logger.debug(f"Processing batch {start_idx//batch_size + 1}/{(total_rows + batch_size - 1)//batch_size}: rows {start_idx} to {end_idx}")

            # convert batch rows into documents
            batch_texts = batch_df[input_columns].apply(self.row_to_document, axis=1)

            try:
                # get embeddings for this batch
                batch_embeddings = model.embed_documents(batch_texts.tolist())
                all_embeddings.extend(batch_embeddings)
                logger.debug(f"Successfully processed batch of {len(batch_embeddings)} embeddings")
            except Exception as e:
                logger.warning(f"Batch processing failed, falling back to individual processing. Error: {str(e)}")
                # If batch fails, try one by one
                batch_embeddings = []
                for i, text in enumerate(batch_texts):
                    try:
                        embedding = model.embed_documents([text])[0]
                        batch_embeddings.append(embedding)
                        logger.debug(f"Successfully processed individual document {start_idx + i}")
                    except Exception as inner_e:
                        # If single document fails, log error
                        logger.error(f"Error embedding document at index {start_idx + len(batch_embeddings)}: {str(inner_e)}")
                        # Raise the error since we can't determine the correct embedding format/size
                        raise Exception(f"Failed to generate embedding for document. Original error: {str(inner_e)}")
                all_embeddings.extend(batch_embeddings)

        logger.info(f"Completed processing {len(all_embeddings)} embeddings")

        # create a new dataframe with the embeddings
        df_embeddings = df.copy().assign(**{target: all_embeddings})
        return df_embeddings

    def row_to_document(self, row: pd.Series) -> str:
        """
        Convert a row in the input dataframe into a document

        Default implementation is to concatenate all the columns
        in the form of
        field1: value1\nfield2: value2\n...
        """
        fields = row.index.tolist()
        values = row.values.tolist()
        document = "\n".join(
            [f"{field}: {value}" for field, value in zip(fields, values)]
        )
        return document

    def finetune(
        self, df: Union[DataFrame, None] = None, args: Union[Dict, None] = None
    ) -> None:
        raise NotImplementedError(
            "Finetuning is not supported for langchain embeddings"
        )

    def describe(self, attribute: Union[str, None] = None) -> DataFrame:
        args = self.model_storage.json_get("args")

        if attribute == "args":
            return pd.DataFrame(args.items(), columns=["key", "value"])
        elif attribute == "metadata":
            return pd.DataFrame(
                [
                    ("model_class", self.model_storage.json_get("model_class")),
                ],
                columns=["key", "value"],
            )

        else:
            tables = ("args", "metadata")
            return pd.DataFrame(tables, columns=["tables"])
