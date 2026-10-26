"""Loads the synthetic store data (products, orders, help-center articles).

The catalog is read-only reference data, so it lives in JSON/markdown files
and is loaded into memory once. Mutable state (returns, escalations,
conversations) lives in SQLite; see store/models.py.
"""

from __future__ import annotations

import json
from datetime import date
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel

from store.retrieval import BM25Index


class Product(BaseModel):
    sku: str
    name: str
    category: str
    price: float
    final_sale: bool
    attributes: dict[str, str]
    description: str


class OrderItem(BaseModel):
    sku: str
    name: str
    quantity: int
    unit_price: float
    final_sale: bool  # snapshot of the terms at purchase time


class Order(BaseModel):
    order_id: str
    email: str
    status: str  # processing | shipped | delivered | cancelled
    order_date: date
    delivered_date: date | None
    tracking_number: str | None
    items: list[OrderItem]

    def item(self, sku: str) -> OrderItem | None:
        return next((i for i in self.items if i.sku == sku), None)


class HelpChunk(BaseModel):
    chunk_id: str  # e.g. "returns-policy#2"
    doc_id: str  # file stem, used for citations
    title: str
    section: str
    text: str


def chunk_article(doc_id: str, markdown: str) -> list[HelpChunk]:
    """Split an article on its `## ` headings: one chunk per section."""
    title = doc_id
    chunks: list[HelpChunk] = []
    section, lines = None, []

    def flush() -> None:
        if section and lines:
            chunks.append(HelpChunk(chunk_id=f"{doc_id}#{len(chunks) + 1}", doc_id=doc_id,
                                    title=title, section=section,
                                    text=" ".join(lines).strip()))

    for line in markdown.splitlines():
        if line.startswith("# "):
            title = line[2:].strip()
        elif line.startswith("## "):
            flush()
            section, lines = line[3:].strip(), []
        elif line.strip():
            lines.append(line.strip())
    flush()
    return chunks


class Catalog:
    def __init__(self, products: list[Product], orders: list[Order], chunks: list[HelpChunk]):
        self.products = products
        self.orders = {o.order_id: o for o in orders}
        self.chunks = chunks
        self.product_index = BM25Index([self._product_text(p) for p in products])
        self.help_index = BM25Index([f"{c.title} {c.section} {c.text}" for c in chunks])

    @staticmethod
    def _product_text(p: Product) -> str:
        attrs = " ".join(f"{k} {v}" for k, v in p.attributes.items())
        return f"{p.name} {p.category} {p.description} {attrs}"

    def search_products(self, query: str, k: int) -> list[Product]:
        return [self.products[i] for i, _ in self.product_index.search(query, k)]

    def search_help(self, query: str, k: int) -> list[HelpChunk]:
        return [self.chunks[i] for i, _ in self.help_index.search(query, k)]

    @classmethod
    def from_dir(cls, data_dir: Path) -> Catalog:
        products = [Product(**p) for p in json.loads((data_dir / "products.json").read_text())]
        orders = [Order(**o) for o in json.loads((data_dir / "orders.json").read_text())]
        chunks: list[HelpChunk] = []
        for path in sorted((data_dir / "help_center").glob("*.md")):
            chunks.extend(chunk_article(path.stem, path.read_text()))
        return cls(products, orders, chunks)


@lru_cache(maxsize=4)
def load_catalog(data_dir: Path) -> Catalog:
    return Catalog.from_dir(data_dir)
