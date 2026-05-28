import siri_server


def test_html_to_plain_strips_bold_tags():
    assert siri_server.html_to_plain("Hola <b>mundo</b>") == "Hola mundo"


def test_html_to_plain_strips_italic_strike_spoiler():
    assert siri_server.html_to_plain("<i>uno</i> <s>dos</s> <tg-spoiler>tres</tg-spoiler>") == "uno dos tres"


def test_html_to_plain_handles_html_entities():
    assert siri_server.html_to_plain("a &lt; b &amp; c &gt; d") == "a < b & c > d"


def test_html_to_plain_leaves_plain_text_alone():
    assert siri_server.html_to_plain("texto sin formato") == "texto sin formato"
