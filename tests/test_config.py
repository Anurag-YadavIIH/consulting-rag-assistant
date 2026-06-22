from consultrag.config import Settings


def test_cors_allowed_origins_list_parses_comma_separated_and_defaults_empty():
    assert Settings(cors_allowed_origins="").cors_allowed_origins_list == []
    assert Settings(
        cors_allowed_origins="http://localhost:3000, http://example.com"
    ).cors_allowed_origins_list == ["http://localhost:3000", "http://example.com"]
