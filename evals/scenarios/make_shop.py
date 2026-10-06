#!/usr/bin/env python3
"""Build the `shop` eval scenario: a small pytest project in a fresh git repo.

    python make_shop.py <dest-dir>

The base commit has four kinds of test behaviour planted in it, and a second
commit (the "change") breaks one more test:

- tests/test_cart.py::test_total_with_discount  broken by the change commit
- tests/test_ids.py::test_order_ids_are_unique   flaky (random id collisions)
- tests/test_b_label.py::test_price_label        order-dependent; polluted by
  tests/test_a_settings.py::test_euro_override
- tests/test_tax.py::test_tax_rounding           already failing on the base commit

Expected verdicts are in evals/evals.json. Needs git and pytest.
"""
import subprocess
import sys
import textwrap
from pathlib import Path

FILES = {
    "shop/__init__.py": "",
    "shop/settings.py": """
        SETTINGS = {"currency": "USD", "symbol": "$"}
    """,
    "shop/cart.py": """
        def total(prices, discount_pct=0):
            \"\"\"Sum prices and apply a whole-cart percentage discount.\"\"\"
            subtotal = sum(prices)
            return round(subtotal * (100 - discount_pct) / 100, 2)
    """,
    "shop/ids.py": """
        import random


        def new_order_id(prefix="ORD"):
            return f"{prefix}-{random.randint(1, 3)}"
    """,
    "shop/labels.py": """
        from shop.settings import SETTINGS


        def price_label(amount):
            return f"{SETTINGS['symbol']}{amount:.2f}"
    """,
    "shop/tax.py": """
        def tax(amount, rate=0.075):
            return int(amount * rate * 100) / 100
    """,
    "tests/__init__.py": "",
    "tests/test_cart.py": """
        from shop.cart import total


        def test_total_without_discount():
            assert total([10, 5.5]) == 15.5


        def test_total_with_discount():
            assert total([19.99, 5], discount_pct=10) == 22.49
    """,
    "tests/test_ids.py": """
        from shop.ids import new_order_id


        def test_order_ids_are_unique():
            assert new_order_id() != new_order_id()


        def test_order_id_prefix():
            assert new_order_id("WEB").startswith("WEB-")
    """,
    "tests/test_a_settings.py": """
        from shop.settings import SETTINGS


        def test_euro_override():
            SETTINGS["currency"] = "EUR"
            SETTINGS["symbol"] = "EUR "
            assert SETTINGS["currency"] == "EUR"
    """,
    "tests/test_b_label.py": """
        from shop.labels import price_label


        def test_price_label():
            assert price_label(3) == "$3.00"
    """,
    "tests/test_tax.py": """
        from shop.tax import tax


        def test_tax_small():
            assert tax(100) == 7.5


        def test_tax_rounding():
            assert tax(19.99) == 1.50
    """,
    "README.md": """
        # shop

        Tiny shop library. Run the tests with `python -m pytest`.
    """,
    ".gitignore": """
        __pycache__/
        .pytest_cache/
        .flake/
    """,
}

CHANGE = {
    "shop/cart.py": """
        def total(prices, discount_pct=0):
            \"\"\"Sum prices and apply a whole-cart percentage discount.

            Discounts now apply per item so they can later vary by item.
            \"\"\"
            return round(sum(p * (100 - discount_pct) // 100 for p in prices), 2)
    """,
}


def write(root: Path, files: dict) -> None:
    for rel, body in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(textwrap.dedent(body).lstrip("\n"), encoding="utf-8")


def git(root: Path, *args) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


def main() -> int:
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    root = Path(sys.argv[1])
    if root.exists() and any(root.iterdir()):
        sys.exit(f"{root} is not empty")
    root.mkdir(parents=True, exist_ok=True)
    write(root, FILES)
    git(root, "init", "-q", "-b", "main")
    git(root, "-c", "user.name=eval", "-c", "user.email=eval@example.com", "add", "-A")
    git(root, "-c", "user.name=eval", "-c", "user.email=eval@example.com",
        "commit", "-q", "-m", "shop: initial")
    git(root, "checkout", "-q", "-b", "per-item-discount")
    write(root, CHANGE)
    git(root, "-c", "user.name=eval", "-c", "user.email=eval@example.com",
        "commit", "-qam", "Apply discount per item")
    print(f"shop scenario at {root} (branch per-item-discount, base main)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
