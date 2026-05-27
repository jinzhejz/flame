from dataclasses import dataclass


@dataclass
class Question:
    topic: str


@dataclass
class Answer:
    answer: str


@dataclass
class WebPage:
    url: str


@dataclass
class Script:
    language: str
    code: str
    runtime: str | None = None
