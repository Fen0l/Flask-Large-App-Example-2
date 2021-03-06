#!/usr/bin/env python2.7
"""Main entry-point into the 'GitHub Status' Flask application.

License: MIT
Website: https://github.com/Robpol86/Flask-Large-App-Example-2

Command details:
    devserver           Run the application using the Flask Development
                        Server. Auto-reloads files when they change.
    prodserver          Run the application with Facebook's Tornado web
                        server. Forks into multiple processes to handle
                        several requests.
    shell               Starts a Python interactive shell with the Flask
                        application context.
    create_all          Only create database tables if they don't exist and
                        then exit.

Usage:
    manage.py devserver [-p NUM] [-l DIR] [--config_prod]
    manage.py prodserver [-p NUM] [-l DIR] [--config_prod]
    manage.py shell [--config_prod]
    manage.py create_all [--config_prod]
    manage.py (-h | --help)

Options:
    --config_prod               Load the production configuration instead of
                                development.
    -l DIR --log_dir=DIR        Log all statements to file in this directory
                                instead of stdout.
                                Only ERROR statements will go to stdout. stderr
                                is not used.
    -p NUM --port=NUM           Flask will listen on this port number.
                                [default: 5000]
"""

from __future__ import print_function
from functools import wraps
import logging
import logging.handlers
import os
import signal
import sys

from docopt import docopt
import flask
from flask.ext.script import Shell
from tornado import httpserver, ioloop, web, wsgi

from github_status.application import create_app, get_config
from github_status.extensions import db

OPTIONS = docopt(__doc__) if __name__ == '__main__' else dict()


def setup_logging(name=None):
    """Setup logging for the entire application.

    Always logs DEBUG statements somewhere.

    Positional arguments:
    name -- Append this string to the log file filename.
    """
    log_to_disk = False
    if OPTIONS['--log_dir']:
        if not os.path.isdir(OPTIONS['--log_dir']):
            print('ERROR: Directory {} does not exist.'.format(OPTIONS['--log_dir']))
            sys.exit(1)
        if not os.access(OPTIONS['--log_dir'], os.W_OK):
            print('ERROR: No permissions to write to directory {}.'.format(OPTIONS['--log_dir']))
            sys.exit(1)
        log_to_disk = True

    fmt = '%(asctime)-15s %(levelname)-8s %(filename)-10s:%(lineno)-2d %(message)s'

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.ERROR if log_to_disk else logging.DEBUG)
    console_handler.setFormatter(logging.Formatter(fmt))

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    root.addHandler(console_handler)

    if log_to_disk:
        file_name = os.path.join(OPTIONS['--log_dir'], 'github_status_{}.log'.format(name))
        file_handler = logging.handlers.TimedRotatingFileHandler(file_name, when='d', backupCount=7)
        file_handler.setFormatter(logging.Formatter(fmt))
        root.addHandler(file_handler)


def log_messages(app, port):
    """Log messages common to Tornado and devserver."""
    log = logging.getLogger(__name__)
    log.info('Server is running at http://0.0.0.0:{}/'.format(port))
    log.info('Flask version: {}'.format(flask.__version__))
    log.info('DEBUG: {}'.format(app.config['DEBUG']))
    log.info('STATIC_FOLDER: {}'.format(app.static_folder))


def parse_options():
    """Parses command line options for Flask.

    Returns:
    Config instance to pass into create_app().
    """
    # Figure out which class will be imported.
    if OPTIONS['--config_prod']:
        config_class_string = 'github_status.config.Production'
    else:
        config_class_string = 'github_status.config.Config'
    config_obj = get_config(config_class_string)

    return config_obj


def command(func):
    """Decorator that registers the chosen command/function.

    If a function is decorated with @command but that function name is not a valid "command" according to the docstring,
    a KeyError will be raised, since that's a bug in this script.

    If a user doesn't specify a valid command in their command line arguments, the above docopt(__doc__) line will print
    a short summary and call sys.exit() and stop up there.

    If a user specifies a valid command, but for some reason the developer did not register it, an AttributeError will
    raise, since it is a bug in this script.

    Finally, if a user specifies a valid command and it is registered with @command below, then that command is "chosen"
    by this decorator function, and set as the attribute `chosen`. It is then executed below in
    `if __name__ == '__main__':`.

    Doing this instead of using Flask-Script.

    Positional arguments:
    func -- the function to decorate
    """
    @wraps(func)
    def wrapped():
        return func()

    # Register chosen function.
    if func.__name__ not in OPTIONS:
        raise KeyError('Cannot register {}, not mentioned in docstring/docopt.'.format(func.__name__))
    if OPTIONS[func.__name__]:
        command.chosen = func

    return wrapped


@command
def devserver():
    setup_logging('devserver')
    app = create_app(parse_options())
    log_messages(app, OPTIONS['--port'])
    app.run(host='0.0.0.0', port=int(OPTIONS['--port']))


@command
def prodserver():
    setup_logging('prodserver')
    app = create_app(parse_options())
    log_messages(app, OPTIONS['--port'])

    # Setup the application.
    container = wsgi.WSGIContainer(app)
    application = web.Application([
        (r'/(favicon\.ico)', web.StaticFileHandler, dict(path=app.static_folder)),
        (r'/static/(.*)', web.StaticFileHandler, dict(path=app.static_folder)),
        (r'.*', web.FallbackHandler, dict(fallback=container))
    ])  # From http://maxburstein.com/blog/django-static-files-heroku/
    http_server = httpserver.HTTPServer(application)
    http_server.bind(OPTIONS['--port'])

    # Start the server.
    http_server.start(0)  # Forks multiple sub-processes
    ioloop.IOLoop.instance().start()


@command
def shell():
    setup_logging('shell')
    app = create_app(parse_options())
    app.app_context().push()
    Shell(make_context=lambda: dict(app=app, db=db)).run(no_ipython=False, no_bpython=False)


@command
def create_all():
    setup_logging('create_all')
    app = create_app(parse_options())
    log = logging.getLogger(__name__)
    with app.app_context():
        tables_before = {t[0] for t in db.session.execute('SHOW TABLES')}
        db.create_all()
        tables_after = {t[0] for t in db.session.execute('SHOW TABLES')}
    created_tables = tables_after - tables_before
    for table in created_tables:
        log.info('Created table: {}'.format(table))


if __name__ == '__main__':
    signal.signal(signal.SIGINT, lambda *_: sys.exit(0))  # Properly handle Control+C
    if not OPTIONS['--port'].isdigit():
        print('ERROR: Port should be a number.')
        sys.exit(1)
    getattr(command, 'chosen')()  # Execute the function specified by the user.
