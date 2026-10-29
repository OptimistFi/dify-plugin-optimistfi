"""What Dify and its Marketplace check, checked here first."""

import os
import re

import pytest
import yaml
from dify_plugin.core.entities.plugin.setup import PluginConfiguration
from dify_plugin.core.utils.yaml_loader import load_yaml_file
from dify_plugin.entities.tool import ToolProviderConfiguration

from conftest import ROOT

LANGUAGES = {"en_US", "zh_Hans", "ja_JP", "pt_BR"}


@pytest.fixture(autouse=True)
def at_root(monkeypatch):
    monkeypatch.chdir(ROOT)


def test_manifest_and_provider_load_with_the_sdks_own_models():
    manifest = PluginConfiguration(**load_yaml_file("manifest.yaml"))
    provider = ToolProviderConfiguration(**load_yaml_file("provider/optimistfi.yaml"))

    assert manifest.name == "optimistfi"
    assert len(provider.tools) == 4


def test_marketplace_metadata_is_present():
    manifest = yaml.safe_load((ROOT / "manifest.yaml").read_text())

    for field in ("privacy", "repo", "contact", "icon", "icon_dark"):
        assert manifest.get(field), field
    assert manifest["network"]["domains"] == ["mcp.optimistfi.com"]
    assert (ROOT / "PRIVACY.md").read_text().strip()
    assert all((ROOT / "_assets" / manifest[k]).is_file() for k in ("icon", "icon_dark"))


def test_every_label_and_description_has_all_four_languages():
    def walk(node, path="tool"):
        if isinstance(node, dict):
            for key, value in node.items():
                if (
                    key in ("label", "human_description", "human", "description")
                    and isinstance(value, dict)
                    and "en_US" in value
                ):
                    assert set(value) == LANGUAGES, f"{path}.{key}: {set(value)}"
                walk(value, f"{path}.{key}")
        elif isinstance(node, list):
            for item in node:
                walk(item, path)

    for path in [
        ROOT / "manifest.yaml",
        ROOT / "provider" / "optimistfi.yaml",
        *sorted((ROOT / "tools").glob("*.yaml")),
    ]:
        walk(yaml.safe_load(path.read_text()), path.name)


# The Marketplace validator routes any package whose own prose matches these to a manual
# financial-activity review (dify-marketplace-toolkit, toolkit/checks/financial.py).
FINANCIAL_PATTERNS = [
    r"\bpayment\s+processing\b",
    r"\bprocess(?:ing)?\s+payments?\b",
    r"\bpayments?\b",
    r"\bcheckout\b",
    r"\bcharge(?:s|d)?\b",
    r"\brefund(?:s|ed)?\b",
    r"\bpayout(?:s)?\b",
    r"\bfinancial\s+transactions?\b",
    r"\btransactions?\b",
    r"\btrading\b",
    r"\btrade\s+(?:stock|crypto|token|asset)s?\b",
    r"\bplace\s+(?:an?\s+)?orders?\b",
    r"\bbuy\s+(?:stock|crypto|token|asset)s?\b",
    r"\bsell\s+(?:stock|crypto|token|asset)s?\b",
    r"\basset\s+transfers?\b",
    r"\btransfer\s+(?:funds?|assets?|money|cash)\b",
    r"\bsend\s+(?:funds?|money|cash)\b",
    r"\bwire\s+transfer\b",
    r"\bwithdraw(?:al|s)?\b",
    r"\bdeposit(?:s)?\b",
    r"\btoken\s+transfers?\b",
    r"\btransfer\s+(?:crypto|tokens?|coins?|nft)s?\b",
    r"\bsend\s+(?:crypto|tokens?|coins?|nft)s?\b",
    r"\bswap\s+(?:crypto|tokens?|coins?)\b",
    r"\bbridge\s+(?:crypto|tokens?|coins?)\b",
    r"\bwallet\s+transfer\b",
]


def packaged_text_files(extra=()):
    ignored = {".venv", "tests", ".git", ".github", "__pycache__", ".pytest_cache", ".ruff_cache", "docs"}
    for folder, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in ignored]
        for name in files:
            if name.endswith((".md", ".yaml", ".yml", ".py", ".toml", ".json", *extra)):
                yield os.path.join(folder, name)


def test_package_prose_stays_clear_of_the_financial_activity_scan():
    hits = []
    for path in packaged_text_files():
        with open(path, encoding="utf-8") as handle:
            for number, line in enumerate(handle, start=1):
                if any(re.search(p, line, re.IGNORECASE) for p in FINANCIAL_PATTERNS):
                    hits.append(f"{os.path.relpath(path, ROOT)}:{number}: {line.strip()[:100]}")
    assert not hits, "\n".join(hits)


# The Marketplace review currently takes no Web3 functionality (langgenius/dify-plugins#3551, 2026-10-29),
# so nothing in the package may describe or call crypto, perps or prop-firm data.
WEB3_PATTERNS = [
    r"\bcrypto",
    r"\bperp",
    r"\bfutures?\b",
    r"\bhyperliquid\b",
    r"\bbitcoin\b",
    r"\b(?:BTC|ETH|SOL)\b",
    r"\bethereum\b",
    r"\bweb3\b",
    r"\bblockchain\b",
    r"\bon-?chain\b",
    r"\bwallets?\b",
    r"\bdefi\b",
    r"\bstablecoins?\b",
    r"\bprop\s+(?:firm|trading|challenge)",
    r"\bfunding\s+rate",
    r"\bliquidations?\b",
    r"\bget_(?:perps|prop_firms)",
    r"加密",
    r"永续",
    r"暗号資産",
    r"無期限先物",
    r"\bcripto",
    r"\bperpétu",
]


def test_package_holds_no_web3_functionality():
    hits = []
    for path in packaged_text_files(extra=(".txt",)):
        with open(path, encoding="utf-8") as handle:
            for number, line in enumerate(handle, start=1):
                if any(re.search(p, line, re.IGNORECASE) for p in WEB3_PATTERNS):
                    hits.append(f"{os.path.relpath(path, ROOT)}:{number}: {line.strip()[:100]}")
    assert not hits, "\n".join(hits)


def test_every_readme_image_is_in_the_package():
    for readme in [ROOT / "README.md", *sorted((ROOT / "readme").glob("*.md"))]:
        for src in re.findall(r'<img src="([^"]+)"', readme.read_text()):
            assert (readme.parent / src).resolve().is_file(), f"{readme.name}: {src}"
