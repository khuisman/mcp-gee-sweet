from . import charts, drive, read, sheets, write


def register_all(tool):
    read.register(tool)
    write.register(tool)
    sheets.register(tool)
    drive.register(tool)
    charts.register(tool)
