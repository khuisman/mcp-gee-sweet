from . import calendar


def register_all(tool):
    from .sheets import data, structure

    data.register(tool)
    structure.register(tool)

    from .drive import activity, files, sharing, transfer

    files.register(tool)
    sharing.register(tool)
    transfer.register(tool)
    activity.register(tool)

    from . import cache, docs

    docs.register(tool)
    cache.register(tool)
    calendar.register(tool)
