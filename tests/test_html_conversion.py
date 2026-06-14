from mcp_gee_sweet.tools.docs import _html_to_doc_requests, _html_to_text


class TestHtmlToText:
    def test_plain_paragraph(self):
        assert _html_to_text("<p>Hello world</p>") == "Hello world"

    def test_multiple_paragraphs(self):
        result = _html_to_text("<p>First</p><p>Second</p>")
        assert "First" in result
        assert "Second" in result
        assert result.index("First") < result.index("Second")

    def test_line_break(self):
        result = _html_to_text("Line one<br>Line two")
        assert "\n" in result

    def test_strips_tags(self):
        result = _html_to_text("<h1>Title</h1><p>Body</p>")
        assert "<h1>" not in result
        assert "Title" in result
        assert "Body" in result

    def test_html_entities(self):
        assert "&amp;" not in _html_to_text("<p>fish &amp; chips</p>")
        assert "fish & chips" in _html_to_text("<p>fish &amp; chips</p>")

    def test_numeric_html_entity(self):
        result = _html_to_text("<p>&#169;</p>")
        assert "©" in result

    def test_empty_input(self):
        assert _html_to_text("") == ""

    def test_plain_text_passthrough(self):
        assert _html_to_text("just text") == "just text"


class TestHtmlToDocRequests:
    def test_empty_input_returns_empty(self):
        requests, tables = _html_to_doc_requests("")
        assert requests == []
        assert tables == []

    def test_paragraph_produces_insert_text(self):
        requests, _ = _html_to_doc_requests("<p>Hello</p>")
        insert = next(r for r in requests if "insertText" in r)
        assert "Hello" in insert["insertText"]["text"]

    def test_h1_produces_heading_1(self):
        requests, _ = _html_to_doc_requests("<h1>Title</h1>")
        styles = [
            r["updateParagraphStyle"]["paragraphStyle"]["namedStyleType"]
            for r in requests
            if "updateParagraphStyle" in r
        ]
        assert "HEADING_1" in styles

    def test_h2_produces_heading_3(self):
        requests, _ = _html_to_doc_requests("<h2>Subtitle</h2>")
        styles = [
            r["updateParagraphStyle"]["paragraphStyle"]["namedStyleType"]
            for r in requests
            if "updateParagraphStyle" in r
        ]
        assert "HEADING_3" in styles

    def test_list_item_produces_bullet(self):
        requests, _ = _html_to_doc_requests("<li>Item</li>")
        bullets = [r for r in requests if "createParagraphBullets" in r]
        assert len(bullets) == 1

    def test_anchor_produces_link_style(self):
        requests, _ = _html_to_doc_requests('<p><a href="https://example.com">click</a></p>')
        links = [
            r
            for r in requests
            if "updateTextStyle" in r and "link" in r["updateTextStyle"].get("textStyle", {})
        ]
        assert len(links) == 1
        assert links[0]["updateTextStyle"]["textStyle"]["link"]["url"] == "https://example.com"

    def test_start_index_offset(self):
        requests_default, _ = _html_to_doc_requests("<p>Hi</p>", start_index=1)
        requests_offset, _ = _html_to_doc_requests("<p>Hi</p>", start_index=10)
        default_insert = next(r for r in requests_default if "insertText" in r)
        offset_insert = next(r for r in requests_offset if "insertText" in r)
        assert offset_insert["insertText"]["location"]["index"] == 10
        assert default_insert["insertText"]["location"]["index"] == 1

    def test_indices_are_contiguous(self):
        requests, _ = _html_to_doc_requests("<p>First</p><p>Second</p>")
        insert = next(r for r in requests if "insertText" in r)
        full_text = insert["insertText"]["text"]
        assert full_text == "First\nSecond\n"

    def test_list_item_inside_ul(self):
        requests, _ = _html_to_doc_requests("<ul><li>Item one</li><li>Item two</li></ul>")
        bullets = [r for r in requests if "createParagraphBullets" in r]
        assert len(bullets) == 2

    def test_whitespace_only_paragraph_skipped(self):
        requests, _ = _html_to_doc_requests("<p>   </p><p>Real content</p>")
        insert = next(r for r in requests if "insertText" in r)
        assert "Real content" in insert["insertText"]["text"]
        assert insert["insertText"]["text"].strip() == "Real content"

    def test_table_produces_insert_table_request(self):
        requests, tables = _html_to_doc_requests(
            "<table><tr><th>A</th><th>B</th></tr><tr><td>1</td><td>2</td></tr></table>"
        )
        table_reqs = [r for r in requests if "insertTable" in r]
        assert len(table_reqs) == 1
        assert table_reqs[0]["insertTable"]["rows"] == 2
        assert table_reqs[0]["insertTable"]["columns"] == 2

    def test_table_data_returned_in_tables(self):
        _, tables = _html_to_doc_requests(
            "<table><tr><th>A</th><th>B</th></tr><tr><td>1</td><td>2</td></tr></table>"
        )
        assert len(tables) == 1
        assert tables[0][0] == ["A", "B"]
        assert tables[0][1] == ["1", "2"]

    def test_table_interleaved_with_text(self):
        html = "<h2>Before</h2><table><tr><td>X</td></tr></table><h2>After</h2>"
        requests, tables = _html_to_doc_requests(html)
        insert_texts = [r for r in requests if "insertText" in r]
        insert_tables = [r for r in requests if "insertTable" in r]
        # All text ("Before\nAfter\n") in one insertText; table inserted between them
        assert len(insert_texts) == 1
        assert len(insert_tables) == 1
        all_text = insert_texts[0]["insertText"]["text"]
        assert "Before" in all_text and "After" in all_text
        # Table position is between the two text segments (after "Before\n" = 7 chars)
        text_start = insert_texts[0]["insertText"]["location"]["index"]
        table_idx = insert_tables[0]["insertTable"]["location"]["index"]
        assert text_start <= table_idx <= text_start + len("Before\n")

    def test_heading_gets_delete_bullets(self):
        requests, _ = _html_to_doc_requests("<h1>Title</h1>")
        has_delete = any("deleteParagraphBullets" in r for r in requests)
        assert has_delete

    def test_paragraph_gets_delete_bullets(self):
        requests, _ = _html_to_doc_requests("<p>Body</p>")
        has_delete = any("deleteParagraphBullets" in r for r in requests)
        assert has_delete

    def test_li_does_not_get_delete_bullets(self):
        requests, _ = _html_to_doc_requests("<li>Item</li>")
        has_delete = any("deleteParagraphBullets" in r for r in requests)
        assert not has_delete

    def test_table_no_cell_inserttext_in_requests(self):
        requests, _ = _html_to_doc_requests("<table><tr><td>hello</td></tr></table>")
        # Cell content must NOT appear in this batch — it goes in a second phase
        cell_inserts = [
            r for r in requests if "insertText" in r and "hello" in r["insertText"].get("text", "")
        ]
        assert cell_inserts == []

    def test_adjacent_tables_order_preserved(self):
        html = "<table><tr><td>T1</td></tr></table><table><tr><td>T2</td></tr></table>"
        requests, tables = _html_to_doc_requests(html)
        insert_tables = [r for r in requests if "insertTable" in r]
        assert len(insert_tables) == 2
        assert len(tables) == 2
        assert tables[0][0][0] == "T1"
        assert tables[1][0][0] == "T2"
        # Both tables share the same insert position (no text between them).
        # Reverse-order insertion means T1 ends up at a lower index than T2 in the doc,
        # so T1's position must be <= T2's position in the request list (last request = T1).
        t1_req = insert_tables[-1]  # inserted last → lands first in doc
        t2_req = insert_tables[-2]  # inserted first → lands second in doc
        assert (
            t1_req["insertTable"]["location"]["index"] <= t2_req["insertTable"]["location"]["index"]
        )
