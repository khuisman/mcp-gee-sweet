from .comments import register as _register_comments
from .content import register as _register_content
from .editing import register as _register_editing
from .images import register as _register_images
from .layout import register as _register_layout
from .named_ranges import register as _register_named_ranges
from .style import register as _register_style
from .tables import register as _register_tables


def register(tool):
    _register_content(tool)
    _register_editing(tool)
    _register_images(tool)
    _register_tables(tool)
    _register_style(tool)
    _register_layout(tool)
    _register_comments(tool)
    _register_named_ranges(tool)
