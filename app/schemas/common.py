import math


def total_paginas(total: int, page_size: int) -> int:
    return math.ceil(total / page_size) if total else 0
