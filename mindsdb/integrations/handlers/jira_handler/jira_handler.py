from typing import Any, Dict

from atlassian import Jira
from requests.exceptions import HTTPError

from mindsdb.integrations.handlers.jira_handler.jira_table import JiraProjectsTable
from mindsdb.integrations.libs.api_handler import APIHandler
from mindsdb.integrations.libs.response import (
    HandlerResponse as Response,
    HandlerStatusResponse as StatusResponse,
)
from mindsdb.utilities import log
from mindsdb_sql_parser import parse_sql


logger = log.getLogger(__name__)


class JiraHandler(APIHandler):
    """
    This handler handles the connection and execution of SQL statements on Jira.
    """

    def __init__(self, name: str, connection_data: Dict, **kwargs: Any) -> None:
        """
        Initializes the handler.

        Args:
            name (Text): The name of the handler instance.
            connection_data (Dict): The connection data required to connect to the Jira API.
            kwargs: Arbitrary keyword arguments.
        """
        super().__init__(name)
        self.connection_data = connection_data
        self.kwargs = kwargs

        self.connection = None
        self.is_connected = False

        jira_projects_data = JiraProjectsTable(self)
        self._register_table("project", jira_projects_data)

    def connect(self) -> Jira:
        """
        Establishes a connection to the Jira API.

        Raises:
            ValueError: If the required connection parameters are not provided.
            AuthenticationError: If an authentication error occurs while connecting to the Salesforce API.

        Returns:
            atlassian.jira.Jira: A connection object to the Jira API.
        """
        if self.is_connected is True:
            return self.connection
        
        is_cloud = self.connection_data.get("cloud", True)

        if is_cloud:
            # Jira Cloud supports API token authentication.
            if not all(key in self.connection_data for key in ['username', 'api_token', 'url']):
                raise ValueError("Required parameters (username, api_token, url) must be provided.")
            
            config = {
                "username": self.connection_data['username'],
                "password": self.connection_data['api_token'],
                "url": self.connection_data['url'],
            }
        else:
            # Jira Server supports personal access token authentication or open access.
            if 'url' not in self.connection_data:
                raise ValueError("Required parameter 'url' must be provided.")
            
            config = {
                "url": self.connection_data['url'],
                "cloud": False
            }

            if 'personal_access_token' in self.connection_data:
                config['session'] = ({"Authorization": f"Bearer {self.connection_data['personal_access_token']}"})

        try:
            self.connection = Jira(**config)
            self.is_connected = True
            return self.connection
        except Exception as unknown_error:
            logger.error(f"Unknown error connecting to Jira, {unknown_error}!")
            raise

    def check_connection(self) -> StatusResponse:
        """
        Checks the status of the connection to the Salesforce API.

        Returns:
            StatusResponse: An object containing the success status and an error message if an error occurs.
        """
        response = StatusResponse(False)

        try:
            connection = self.connect()
            connection.myself()
            response.success = True
        except (HTTPError, ValueError) as known_error:
            logger.error(f'Connection check to Jira failed, {known_error}!')
            response.error_message = str(known_error)
        except Exception as unknown_error:
            logger.error(f'Connection check to Jira failed due to an unknown error, {unknown_error}!')
            response.error_message = str(unknown_error)

        self.is_connected = response.success

        return response

    def native_query(self, query: str) -> Response:
        """Receive and process a raw query.
        Parameters
        ----------
        query : str
            query in a native format
        Returns
        -------
        StatusResponse
            Request status
        """
        ast = parse_sql(query)
        return self.query(ast)
   
    def construct_jql(self):
        """construct jql & returns it to JiraProjectsTable class
        Returns
        -------
        Str
        """
        return 'project = ' + str(self.connection_data['project'])
