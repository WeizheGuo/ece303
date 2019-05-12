import datetime
import logging


class Logger(object):

    def __init__(self, name, debug_level):
        now = datetime.datetime.now()
        logging.basicConfig(filename='{}_{}.log'.format(name, datetime.datetime.strftime(now, "%Y_%m_%dT%H%M%S")),
                            format   = '%(asctime)s  %(filename)s : %(levelname)s  %(message)s',
                            level=debug_level)
        # formatter = logging.Formatter('%(asctime)s  %(filename)s : %(levelname)s  %(message)s')

    @staticmethod
    def info(message):
        logging.info(message)

    @staticmethod
    def debug(message):
        logging.debug(message)
