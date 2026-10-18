"""Dedicated SMTP worker: python -m dashboard.mail.worker [--once]."""
import argparse
import time

from . import MailError
from .outbox import claim,finish
from .transport import deliver


def run_once(app,now=None):
    with app.app_context():
        config=app.extensions['dashboard_mail']
        if not config.enabled:raise MailError('Email is not configured; worker remains stopped.')
        claimed=claim(config,now)
        if claimed is None:return False
        outcomes=deliver(config,claimed['message'],claimed['recipients'])
        finish(config,claimed,outcomes,now)
        return True


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--once',action='store_true')
    args=parser.parse_args(argv)
    from app import app
    try:
        while True:
            worked=run_once(app)
            if args.once:return 0
            if not worked:time.sleep(1)
    except MailError as error:
        parser.exit(1,str(error)+'\n')
    except KeyboardInterrupt:return 0


if __name__=='__main__':raise SystemExit(main())
