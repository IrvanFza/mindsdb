from typing import List
from textwrap import dedent
from datetime import datetime

from langchain_community.agent_toolkits.sql.toolkit import SQLDatabaseToolkit
from langchain_community.tools import ListSQLDatabaseTool, InfoSQLDatabaseTool, QuerySQLDataBaseTool
from langchain_core.tools import BaseTool

from mindsdb.interfaces.skills.custom.text2sql.mindsdb_sql_tool import MindsDBSQLParserTool


class MindsDBSQLToolkit(SQLDatabaseToolkit):

    def get_tools(self, prefix='') -> List[BaseTool]:

        current_date_time = datetime.now().strftime("%Y-%m-%d %H:%M")

        """Get the tools in the toolkit."""
        list_sql_database_tool = ListSQLDatabaseTool(
            name=f'sql_db_list_tables{prefix}',
            db=self.db,
            description=dedent("""\n
                Input is an empty string, output is a comma-separated list of tables in the database. Each table name is escaped using backticks.
                Each table name in the list may be in one of two formats: database_name.`table_name` or database_name.schema_name.`table_name`.
                Table names in response to the user must be escaped using backticks.
            """)
        )

        info_sql_database_tool_description = (
            "Input: A comma-separated list of tables enclosed between the symbols $START$ and $STOP$. The tables names itself must be escaped using backticks.\n"
            "Output: Schema and sample rows for those tables. \n"
            "Use this tool to investigate table schemas for needed columns. "
            f"Ensure tables exist by calling {list_sql_database_tool.name} first. "
            # "The names of tables, schemas, and databases must be escaped using backticks. "
            # "Always enclose the names of tables, schemas, and databases in backticks. "
            "Get sample data with 'SELECT * FROM `database`.`table` LIMIT 3' before answering questions. \n"
            "Example of correct Input:\n    $START$ `database`.`table1`, `database`.`table2`, `database`.`table3` $STOP$\n"
            "    $START$ `table1` `table2` `table3` $STOP$\n"
            "Example of wrong Input:\n    $START$ `database.table1`, `database.table2`, `database.table3` $STOP$\n"
            "    $START$ table1 table2 table3 $STOP$\n"
        )
        info_sql_database_tool = InfoSQLDatabaseTool(
            name=f'sql_db_schema{prefix}',
            db=self.db, description=info_sql_database_tool_description
        )

        query_sql_database_tool_description = dedent(f"""\
            Input: A detailed and well-structured SQL query. The query must be enclosed between the symbols $START$ and $STOP$.
            Output: Database result or error message. For errors, rewrite and retry the query. For 'Unknown column' errors, use '{info_sql_database_tool.name}' to check table fields.
            This system is a highly intelligent and reliable PostgreSQL SQL skill designed to work with databases.
            Follow these instructions with utmost precision:
            1. Final Response Format:
               - Assume the frontend fully supports Markdown unless the user specifies otherwise.
               - When the response contains data that fits a table format, present it as a properly formatted Markdown table
                   - Ensure clarity and proper structure for easy readability.
                   - After you pesent a table, if you believe that the data can be visualized:
                       -always generate a Chart.js configuration and include it in the Markdown response as follows:
                            ```chartjs
                            {{<chartjs config>}}
                            ```
                       - when presenting a chart:
                            - never mention anything about chart.js or it's configuration, 
                            - the front end will render that config into a chart, so when you refer to it, always refer to it as a chart, not a config.
                            - BEFORE visualizing information use as much as possible the database to sort information, using ORDER BY
               - Always wrap mathematical expressions and/or formulas, in $ or $$ as follows:
                  - Inline: ${expression}$
                  - Block: $${expression}$$
                  - For example: 
                       - instead of:  \text{pe c} =\frac{R}{B},    do $$ \text{pe c} =\frac{R}{B}$$
                       - instead of: where ( \Delta U ) is the change, do: where ( $\Delta U$ ) is the change
            2. Sample Data:
               - Before answering a question, if you don't have sample data about a table, **always** get sample data using `SELECT * FROM table LIMIT 3` from the tables you believe are relevant to formulating your answers.
            3. Categorical Data:
               - Whenever working with a column where values seem categorical, especially when filtering with `WHERE col = 'value'`, `WHERE col IN (list of values)`, or `WHERE col NOT IN (list of values)`, **always** retrieve the distinct values first.
               - Before writing your main query, always run `SELECT DISTINCT col` to fetch a list of unique values from that column. This step is mandatory to ensure accurate queries and responses.
            4. Result Limiting and Counting:
               - Unless instructed otherwise by the user, always run a count on the final query first using `SELECT COUNT(*)`.
               - If the count is greater than 10, limit the query to return only 10 results initially.
               - **Always** inform the user of the total number of results available and specify that you are providing the first 10 results.
               - Let the user know they can request additional results and/or specify how they would like the results ordered or grouped.
            5. Date Handling:
               - **System current date and time: {current_date_time} (UTC or local timezone based on server settings).**
               - **Always** use PostgreSQL-compatible `CURRENT_DATE` or `NOW()` functions when working with dates—never assume or guess the current date.
               - For any date-related comparisons in the query, *always* ensure that your query casts the column being compared using `column_name::DATE [operator] ..`
               - Do not compare date values without casting columns to date.
               - For date interval operations, use Interval units as keywords. You can use keywords to specify units like days, hours, months, years, etc., directly without quotes. Examples:
                 SELECT NOW() + INTERVAL 5 DAY;
                 SELECT NOW() - INTERVAL 3 HOUR;
                 SELECT NOW() + INTERVAL 2 MONTH + INTERVAL 3 DAY;
                 SELECT NOW() - INTERVAL 1 YEAR;
               - Always run SELECT NOW() to retrieve the current date when answering current or relative to current date-related questions.
            6. Query Best Practices:
               - Always send only one query at a time.
               - Always enclose the names of tables, schemas, and databases in backticks.
               - The input SQL query must end with a semicolon.
               - Query only necessary columns, not all.
               - Use only existing column names from correct tables.
               - Use database-specific syntax for date operations.
               - Always try to use ORDER BY to sort information when possible and relevant
               - If you need to FILTER always use CASE instead
               - Never use of double quotes for column names use backticks instead.
               - Always give aliases in lower-case underscore notation, no quotes or backticks for alias that are in lowe-case underscore notation.
                  - For example: instead of SELECT COUNT(*) AS `count` do SELECT COUNT(*) AS count
               - For any calculations, always use the database:
                  - Leverage window functions when necessary, and aggregate operations like OVER(). 
                  - For percentages, make sure to safe guard division by zero using nullif(a, b)
               - When asked about distributions, also include calculated percentages, which you should calculate in the query
            7. Error Handling:
               - For errors, rewrite and retry the query.
               - For 'Unknown column' errors, check table fields using info_sql_database_tool.
            8. Identity and Purpose:
               - When asked about yourself or your maker, state that you are a Data-Mind, created by MindsDB to help answer data questions.
               - When asked about your purpose or how you can help, explore the available data sources and then explain that you can answer questions based on the connected data. Provide a few relevant example questions that you could answer for the user about their data.
            Adhere to these guidelines for all queries and responses. Ask for clarification if needed.
        """)

        query_sql_database_tool = QuerySQLDataBaseTool(
            name=f'sql_db_query{prefix}',
            db=self.db, description=query_sql_database_tool_description
        )

        mindsdb_sql_parser_tool_description = (
            "Use this tool to ensure a SQL query passes the MindsDB SQL parser. "
            "If the query is not correct, it will be corrected and returned. Use the new query. "
            "If the query can't be corrected, an error is returned. In this case, rewrite and retry. "
            "If the query is correct, it will be parsed and returned. "
            f"ALWAYS run this tool before executing a query with {query_sql_database_tool.name}. "
        )
        mindsdb_sql_parser_tool = MindsDBSQLParserTool(
            name=f'mindsdb_sql_parser_tool{prefix}',
            description=mindsdb_sql_parser_tool_description
        )

        return [
            query_sql_database_tool,
            info_sql_database_tool,
            list_sql_database_tool,
            mindsdb_sql_parser_tool,
        ]
