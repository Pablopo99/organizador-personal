import formatting


def test_markdown_to_html_converts_bold():
    assert formatting.markdown_to_html("hola **mundo**") == "hola <b>mundo</b>"


def test_markdown_to_html_handles_multiple():
    out = formatting.markdown_to_html("**A** y **B**")
    assert out == "<b>A</b> y <b>B</b>"


def test_markdown_to_html_multiline():
    out = formatting.markdown_to_html("**línea1\nlínea2**")
    assert out == "<b>línea1\nlínea2</b>"


def test_markdown_to_html_leaves_plain_alone():
    assert formatting.markdown_to_html("sin formato") == "sin formato"
