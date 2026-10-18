"""Lazy import aliases for extracted packages; no private code is bundled here."""
from importlib import import_module
from importlib.abc import Loader, MetaPathFinder
from importlib.util import find_spec, spec_from_loader
import sys

ALIASES = {
    'dashboard.four_ad': 'dashboard_private_widgets.four_ad',
    'dashboard.flashcards': 'dashboard_private_widgets.flashcards',
    'dashboard.zettelkasten': 'dashboard_private_widgets.zettelkasten',
    'dashboard.paint_rack': 'dashboard_private_widgets.paint_rack',
    'dashboard.chapter_painter': 'dashboard_private_widgets.chapter_painter',
    'dashboard.notebook_covers': 'dashboard_private_widgets.notebook_covers',
    'dashboard.campaign_tools.frostgrave_models': 'dashboard_private_widgets.frostgrave.models',
    'dashboard.campaign_tools.frostgrave_routes': 'dashboard_private_widgets.frostgrave.routes',
    'dashboard.campaign_tools.rdt_models': 'dashboard_private_widgets.rdt.models',
    'dashboard.campaign_tools.rdt_routes': 'dashboard_private_widgets.rdt.routes',
}


class _AliasLoader(Loader):
    def __init__(self, target):
        self.target = target
    def create_module(self, spec):
        module = import_module(self.target)
        self.original_spec = module.__spec__
        return module
    def exec_module(self, module):
        module.__spec__ = self.original_spec


class _LegacyFinder(MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        for old, new in ALIASES.items():
            if fullname == old or fullname.startswith(old + '.'):
                canonical = new + fullname[len(old):]
                try:
                    original = find_spec(canonical)
                except ModuleNotFoundError:
                    return None
                if original is not None:
                    return spec_from_loader(fullname, _AliasLoader(canonical),
                                            is_package=original.submodule_search_locations is not None)
        return None


def install():
    if not any(isinstance(finder, _LegacyFinder) for finder in sys.meta_path):
        sys.meta_path.insert(0, _LegacyFinder())


def available(name):
    try:
        return find_spec('dashboard_private_widgets.' + name) is not None
    except ModuleNotFoundError:
        return False
