# Contributing to hypr-opaque-media

Thank you for your interest in contributing to hypr-opaque-media! This document provides guidelines for contributing to the project.

## Ground Rules

- **Be respectful**: Treat all contributors and users with respect and courtesy.
- **Test your changes**: Ensure all tests pass before submitting a pull request.
- **Follow the code style**: Use the project's formatting and linting tools.
- **Write clear commit messages**: Follow conventional commit format when possible.
- **Update documentation**: Keep documentation up-to-date with your changes.

## Development Setup

### Prerequisites

- Python 3.9 or higher
- Git

### Setting up your development environment

1. Fork the repository on GitHub
2. Clone your fork locally:
   ```bash
   git clone https://github.com/YOUR_USERNAME/hypr-opaque-media.git
   cd hypr-opaque-media
   ```

3. Create a virtual environment:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

4. Install development dependencies:
   ```bash
   pip install ruff black pytest watchdog
   ```

5. Optionally, install pre-commit hooks:
   ```bash
   pip install pre-commit
   pre-commit install
   ```

## Running Linters and Tests

### Linting and Formatting

Before committing, ensure your code passes all checks:

```bash
# Run ruff linter
ruff check .

# Run ruff with auto-fix (recommended)
ruff check --fix .

# Check formatting with Black
black --check .

# Apply Black formatting
black .
```

### Running Tests

```bash
# Run all tests
pytest

# Run tests with verbose output
pytest -v

# Run specific test file
pytest test/test_core.py

# Run tests with coverage (requires pytest-cov)
pip install pytest-cov
pytest --cov=. --cov-report=html
```

The tests use mocking to simulate Hyprland interactions, so you don't need a running Hyprland session.

## Commit Style

We follow [Conventional Commits](https://www.conventionalcommits.org/) format:

```
<type>[optional scope]: <description>

[optional body]

[optional footer(s)]
```

### Types:
- `feat`: New feature
- `fix`: Bug fix
- `docs`: Documentation changes
- `style`: Code style changes (formatting, etc.)
- `refactor`: Code refactoring
- `test`: Adding or updating tests
- `chore`: Maintenance tasks

### Examples:
```
feat: add support for new window class matching
fix: resolve race condition in tag assignment
docs: update README with new configuration options
```

## Pull Requests

### Before submitting:

1. Ensure all tests pass
2. Verify linting passes (`ruff check .`)
3. Verify formatting is correct (`black --check .`)
4. Update documentation if needed
5. Add tests for new functionality

### Pull Request Process:

1. Create a descriptive title and detailed description
2. Reference any related issues
3. Include steps to test your changes
4. Be prepared to address review feedback

### Pull Request Checklist:

- [ ] Tests pass locally
- [ ] Code follows project style guidelines
- [ ] Documentation has been updated (if needed)
- [ ] Changes have been tested manually (if applicable)
- [ ] Commit messages follow conventional format

## Reporting Bugs

When reporting bugs, please include:

1. **Environment information**:
   - Linux distribution and version
   - Hyprland version (`hyprctl version`)
   - Python version (`python --version`)
   - Whether watchdog is installed (`pip show watchdog`)

2. **Configuration**:
   - Your `hypr-opaque-media.json` config (sanitize any sensitive info)
   - Relevant Hyprland configuration rules

3. **Steps to reproduce**: Clear steps to reproduce the issue

4. **Expected vs actual behavior**: What you expected vs what happened

5. **Logs**: Any relevant error messages or logs

## Feature Requests

We welcome feature requests! Please:

1. Check if the feature already exists or is planned
2. Describe the problem you're trying to solve
3. Provide a clear description of the proposed solution
4. Consider alternatives and explain why your approach is preferred

## Questions or Need Help?

- Check the [README.md](README.md) for usage information
- Look through existing issues for similar questions
- Create a new issue with the "question" label

Thank you for contributing! 🎉