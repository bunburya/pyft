from logging import ERROR
from typing import List, Dict, Any, Optional, Tuple, Callable

import dash
import dash_bootstrap_components as dbc
import dash_core_components as dcc
import dash_html_components as html
from all_activities import AllActivitiesController
from dash import callback_context
from dash.development.base_component import Component
from dash.dependencies import Input, Output, ALL, MATCH, State
from dash.exceptions import PreventUpdate

from shyft.activity import ActivityMetaData, Activity
from shyft.activity_manager import ActivityManager
from shyft.config import Config
from shyft.logger import get_logger
from shyft.message import MessageBus
from shyft.view.controller.activity import ActivityController
from shyft.view.controller.config import ConfigController
from shyft.view.controller.overview import OverviewController
from shyft.view.controller.upload import UploadController

logger = get_logger(__name__)


def id_str_to_int(id: str) -> int:
    """Convert a string activity id to an integer, performing some
    basic verification and raising a ValueError is the given id is
    not valid (ie, the string cannot be converted to a valid integer;
    the returned integer is not necessarily the id of an actual
    Activity).
    """
    try:
        activity_id = int(id)
    except (ValueError, TypeError):
        activity_id = None
    if activity_id is None:
        raise ValueError(f'Bad activity id: "{id}".')
    return activity_id

class DashController:
    """A main controller class for use with our Dash app. This will
    hold instances of the other, page-specific controller classes.
    """

    def __init__(self, dash_app: dash.Dash, config: Config, activity_manager: Optional[ActivityManager] = None):
        logger.debug('Initialising DashController.')
        self.dash_app = dash_app
        # Stop Dash complaining if not all components are present when callbacks are registered
        # https://dash.plotly.com/callback-gotchas
        dash_app.config.suppress_callback_exceptions = True
        if activity_manager is None:
            self.activity_manager = ActivityManager(config)
        else:
            self.activity_manager = activity_manager
        self.config = config
        self.config_fpath = config.ini_fpath
        self.msg_bus = MessageBus()

        self.overview_controller = OverviewController(self)
        self.activity_controller = ActivityController(self)
        self.upload_controller = UploadController(self)
        self.config_controller = ConfigController(self)
        self.all_activities_controller = AllActivitiesController(self)
        #self.locations = self.init_locations()
        self.register_callbacks()

        # Initialise with empty layout; content will be added by callbacks.
        self.dash_app.layout = self.layout()

    def init_locations(self) -> List[dcc.Location]:
        return [
            # Because Dash only allows each component property (such as the "pathname" property of a dcc.Location)
            # to be associated with one Output, each part of the app needs to update a separate dcc.Location when
            # it wants to redirect the user, and the relevant callback needs to fire upon any of those components
            # being updated. And we need to create all relevant dcc.Location instances at the beginning.
            dcc.Location(id='upload_location', refresh=False),
            dcc.Location(id='recent_action_location', refresh=True),
            dcc.Location(id='all_action_location', refresh=True),
        ]

    def layout(self, content: Optional[List[Component]] = None) -> html.Div:
        logger.debug('Setting page layout.')
        return html.Div(
            id='layout',
            children=[
                #*self.locations,
                dcc.Location('url', refresh=True),
                html.Div(id='page_content', children=content or [])
            ]
        )

    def _id_str_to_metadata(self, id: str) -> Optional[ActivityMetaData]:
        return self.activity_manager.get_metadata_by_id(id_str_to_int(id))

    def _id_str_to_activity(self, id: str) -> Optional[Activity]:
        return self.activity_manager.get_activity_by_id(id_str_to_int(id))

    def _resolve_pathname(self, path) -> List[Component]:
        """Resolve the URL pathname and return the appropriate page
        content.
        """
        logger.info(f'Resolving pathname "{path}" for page content.')

        if path is not None:
            tokens = path.split('/')[1:]
            if tokens[0] == 'activity':
                try:
                    return self.activity_controller.page_content(self._id_str_to_activity(tokens[1]))
                except IndexError:
                    logger.error('Could not load activity view: No activity ID provided.')
                    self.msg_bus.add_message('Could not display activity. Check the logs for more details.',
                                             severity=ERROR)
                except ValueError:
                    logger.error(f'Could not load activity view: Bad activity ID "{tokens[1]}".')
                    self.msg_bus.add_message('Could not display activity. Check the logs for more details.',
                                             severity=ERROR)
            elif tokens[0] == 'upload':
                return self.upload_controller.page_content()
            elif tokens[0] == 'config':
                return self.config_controller.page_content()
            elif tokens[0] == 'all':
                return self.all_activities_controller.page_content()
            elif tokens[0] in {'gpx_files', 'tcx_files', 'source_files'}:
                raise PreventUpdate
            elif tokens[0]:
                logger.warning(f'Received possibly unexpected pathname "{tokens[0]}".')

        return self.overview_controller.page_content()

    def register_callbacks(self):
        logger.debug('Registering app-level callbacks.')

        @self.dash_app.callback(
            Output('page_content', 'children'),
            Input('url', 'pathname'),
        )
        def update_page(pathname: str) -> List[Component]:
            """Display different page on url update."""
            logger.debug(f'URL change detected: new pathname is "{pathname}".')
            return self._resolve_pathname(pathname)

        @self.dash_app.callback(
            Output('url', 'pathname'),
            Input({'type': 'redirect', 'context': ALL, 'index': ALL}, 'children')
        )
        def update_url(pathnames: List[str]) -> str:
            ctx = dash.callback_context
            trig = ctx.triggered[0]
            component, prop = trig['prop_id'].split('.')
            value = trig['value']
            logger.debug(f'update_url called from property "{prop}" of component "{component}" with value "{value}".')
            #logger.debug(f'pathnames: {pathnames}')
            return value

        # The below callbacks are used for manipulating activity tables. They are registered here in the main controller
        # because activity tables can be manipulated in multiple contexts.

        # @self.dash_app.callback(
        #     Output({'type': 'activity_table', 'index': MATCH}, 'selected_rows'),
        #     Input({'type': 'select_all_button', 'index': MATCH}, 'n_clicks'),
        #     Input({'type': 'unselect_all_button', 'index': MATCH}, 'n_clicks'),
        # )
        # def un_select(*args) -> List[int]:
        #     trig = callback_context.triggered[0]
        #     component, prop = trig['prop_id'].split('.')
        #     logger.debug(f'un_select called with trigger "{trig["prop_id"]}".')
        #     if component == select_id:
        #         logger.debug('Select button clicked.')
        #         return list(range(len(metadata_list)))
        #     elif component == unselect_id:
        #         logger.debug('Unselect button clicked.')
        #         return []
        #     else:
        #         logger.error(f'Unexpected component: "{component}".')
        #         raise PreventUpdate

        @self.dash_app.callback(
            Output({'type': 'redirect', 'context': 'activity_table', 'index': MATCH}, 'children'),
            Input({'type': 'activity_table_dropdown', 'index': MATCH}, 'value'),
            State({'type': 'activity_table', 'index': MATCH}, 'selected_rows'),
            State({'type': 'activity_table', 'index': MATCH}, 'data')
        )
        def action(value, selected_rows, data) -> str:
            logger.debug(f'Value "{value}" selected from dropdown.')
            #logger.debug(f'data: {data}')
            if value == 'select':
                raise PreventUpdate
            ids = [str(data[i]['id']) for i in selected_rows]
            if not ids:
                raise PreventUpdate
            ids_str = ','.join(ids)
            return f'/{value}/{ids_str}'

        # Unfortunately this seems to be the only way to dynamically set the title in Dash.
        # FIXME: Doesn't work...
        # self.dash_app.clientside_callback(
        #     """
        #     function(pathname) {
        #         console.log('Callback called with %s', pathname);
        #         token = pathname.split('/')[1];
        #         if (token === 'activity') {
        #             document.title = 'View activity - Shyft'
        #         } else if (token === 'config') {
        #             document.title = 'Configure - Shyft'
        #         } else if (token === 'upload') {
        #             document.title = 'Upload - Shyft'
        #         } else {
        #             document.title == 'Overview - Shyft'
        #         }
        #     }
        #     """,
        #     Output('dummy', 'children'),
        #     Input('url', 'pathname')
        # )
