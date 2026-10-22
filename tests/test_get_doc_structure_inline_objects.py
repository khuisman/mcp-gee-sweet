"""#1070: get_doc_structure must report an inline image with its own index.

Kept apart from test_docs_content.py, which fails to collect on Windows because
of a POSIX-only ``os.geteuid()`` skipif in an unrelated class.
"""

from unittest.mock import MagicMock

from mcp_gee_sweet.tools import docs as docs_module


def _make_tool_registry():
    captured = {}

    def tool(annotations=None, local_only=False):
        def decorator(func):
            captured[func.__name__] = func
            return func

        return decorator

    return tool, captured


_docs_tool, _docs_tools = _make_tool_registry()
docs_module.register(_docs_tool)


def _make_ctx(docs_service):
    ctx = MagicMock()
    ctx.request_context.lifespan_context.docs_service = docs_service
    return ctx


class TestGetDocStructureInlineObject:
    async def test_inline_image_reported_as_run_with_own_index(self):
        docs_svc = MagicMock()
        docs_svc.documents.return_value.get.return_value.execute.return_value = {
            "documentId": "doc1",
            "title": "Doc",
            "body": {
                "content": [
                    {
                        "startIndex": 1,
                        "endIndex": 4,
                        "paragraph": {
                            "paragraphStyle": {"namedStyleType": "NORMAL_TEXT"},
                            "elements": [
                                {
                                    "startIndex": 1,
                                    "endIndex": 2,
                                    "textRun": {"content": "\t", "textStyle": {}},
                                },
                                {
                                    "startIndex": 2,
                                    "endIndex": 3,
                                    "inlineObjectElement": {"inlineObjectId": "kix.img1"},
                                },
                                {
                                    "startIndex": 3,
                                    "endIndex": 4,
                                    "textRun": {"content": "\n", "textStyle": {}},
                                },
                            ],
                        },
                    }
                ]
            },
        }
        result = await _docs_tools["get_doc_structure"](doc_id="doc1", ctx=_make_ctx(docs_svc))
        image_runs = [r for r in result["elements"][0]["runs"] if r.get("type") == "inlineObject"]
        assert image_runs == [
            {
                "type": "inlineObject",
                "inlineObjectId": "kix.img1",
                "startIndex": 2,
                "endIndex": 3,
                "text": "",
                "bold": None,
                "italic": None,
                "underline": None,
                "strikethrough": None,
                "font_size": None,
                "link_url": None,
            }
        ]
