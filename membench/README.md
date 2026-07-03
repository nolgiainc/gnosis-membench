# membench

Benchmark harness package for gnosis. See the repository root `README.md` for
full usage, protocol notes, and published comparison numbers.

```
uv sync
uv run membench download --benchmark locomo
uv run membench run --benchmark locomo --subset 1 --conditions context,search
```
