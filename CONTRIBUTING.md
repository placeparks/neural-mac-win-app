# Contributing to NeuralClaw

Thanks for your interest in contributing to NeuralClaw! Here's how to get started.

## Development Setup

```bash
git clone https://github.com/placeparks/neuralclaw.git
cd neuralclaw
pip install -e ".[dev]"
```

## Running Tests

```bash
# Full test suite
pytest tests/ -v

# Specific module
pytest tests/test_perception.py -v

# With coverage
pytest tests/ --cov=neuralclaw --cov-report=term-missing
```

## Code Style

We use [Ruff](https://docs.astral.sh/ruff/) for linting:

```bash
ruff check neuralclaw/
ruff format neuralclaw/
```

- **Python 3.12+** required
- Type hints on all public functions
- Docstrings on all modules, classes, and public methods
- Max line length: 100 characters

## Architecture Overview

NeuralClaw uses a **5-cortex cognitive architecture**:

```
Perception → Memory → Reasoning → Action → Evolution
```

All cortices communicate through the **Neural Bus** (async pub/sub). When adding features:

1. **New cortex capabilities** → Add to the appropriate cortex directory
2. **New event types** → Add to `bus/neural_bus.py::EventType`
3. **New skills** → Add to `skills/builtins/` or publish via the marketplace
4. **New channels** → Implement the `ChannelAdapter` protocol in `channels/protocol.py`

## Pull Request Process

1. Fork the repo and create a feature branch from `main`
2. Add tests for any new functionality
3. Ensure all tests pass: `pytest tests/ -v`
4. Ensure code passes linting: `ruff check neuralclaw/`
5. Update the README if adding user-facing features
6. Open a PR with a clear description

## Security

If you discover a security vulnerability, please report it privately — do **not** open a public issue. Email: mirac@cardify.dev

## Skill Contributions

When contributing skills to the marketplace:

- Skills must declare all required capabilities in their manifest
- No shell execution or network access without explicit declaration
- All skills are statically analyzed before acceptance
- Sign your skills with Ed25519 for verified author status

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
