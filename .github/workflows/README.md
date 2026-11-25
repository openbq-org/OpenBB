# OpenBB Workflows

This directory contains the workflows for the OpenBB 🦋 Project. The workflows are:

## 📑 Deploy to GitHub Pages

This GitHub Actions workflow is responsible for building the documentation and deploying it to GitHub Pages. This workflow is triggered when a new change is pushed to the `main` or `release` branch of the repository, and the documentation is published to GitHub Pages.

## Branch Name Check

Objective: To check if pull request branch names follow the GitFlow naming convention before merging.

Triggered by: A pull request event where the target branch is either develop or main.

Branches checked: The source branch of a pull request and the target branch of a pull request.

Steps:

1. Extract branch names: Using the jq tool, the source and target branch names are extracted from the pull request event. The branch names are then stored in environment variables and printed as output.

2. Show Output result for source-branch and target-branch: The source and target branch names are printed to the console.

3. Check branch name for develop PRs: If the target branch is develop, then the source branch is checked against a regular expression to ensure that it follows the GitFlow naming convention. If the branch name is invalid, a message is printed to the console and the workflow exits with a status code of 1.

4. Check branch name for main PRs: If the target branch is main, then the source branch is checked against a regular expression to ensure that it is either a hotfix or a release branch. If the branch name is invalid, a message is printed to the console and the workflow exits with a status code of 1.

Note: The GitFlow naming convention for branches is as follows:

- Feature branches: feature/<feature-name>
- Hotfix branches: hotfix/<hotfix-name>
- Release branches: release/<major.minor.patch>(rc<number>)

## Deploy to PyPI - Nightly

This workflow is used to publish the latest version of the OpenBB Platform CLI to PyPI. The workflow is triggered at UTC+0 daily by the GitHub Action schedule event.

It does this by first updating the `pyproject.toml` file with a pre-determined version string of the form `<currentVersion>.dev<date>`, where `<date>` represents the current day's date as a 8 digit number.

Then, the code installs `pypa/build` and uses `python -m build` to create a binary wheel and a source tarball in the `dist/` directory.

Finally, it uses the PyPA specific action `gh-action-pypi-publish` to publish the created files to PyPI.

## Deploy the OpenBB Platform to Test PyPI

The Github Action code `Deploy to PyPI` is used to deploy a Python project to PyPI (Python Package Index) and TestPyPI, which is a separate package index for testing purposes. The code is triggered on two events:

1. Push event: The code is triggered whenever there is a push to the `release/*` and `main` branches.

2. Workflow dispatch event: The code can be manually triggered by the workflow dispatch event.

The code sets the concurrency to the `group` and the option `cancel-in-progress` is set to `true` to ensure that the running jobs in the same `group` are cancelled in case another job is triggered.

The code contains two jobs, `deploy-test-pypi` and `deploy-pypi`, both of which have the same steps with slight variations.

The `deploy-test-pypi` job is triggered only if the pushed branch starts with `refs/heads/release/`. This job sets up the Python environment, installs the `build` package using `pip`, builds binary wheel and source tarball using `build`, and finally, publishes the distributions to TestPyPI using the `pypa/gh-action-pypi-publish@release/v1` Github Action. The `password` to access TestPyPI is stored as a secret named `TEST_PYPI_API_TOKEN`.

Similarly, the `deploy-pypi` job is triggered only if the pushed branch starts with `refs/heads/main`. This job follows the same steps as `deploy-test-pypi`, but the distributions are published to PyPI instead of TestPyPI. The `password` to access PyPI is stored as a secret named `PYPI_API_TOKEN`.

Note: The code uses the `pypa/build` package for building the binary wheel and source tarball, and the `pypa/gh-action-pypi-publish@release/v1` Github Action for publishing the distributions to PyPI and TestPyPI.

## Draft release

This GitHub Actions workflow is designed to automatically generate and update draft releases in a GitHub repository. The workflow is triggered when it is manually dispatched, allowing you to control when the draft releases are updated.

## 🧹 General Linting

This GitHub Actions workflow is responsible for running linting checks on the codebase. This workflow is triggered on pull request events such as `opened`, `synchronize`, and `edited`, and push events on branches with names that start with `feature/`, `hotfix/`, or `release/`. The workflow also sets a number of environment variables and uses Github Actions caching to improve performance.

It consists of two jobs: `code-linting` and `markdown-link-check`.

The first job, `code-linting`, runs on an Ubuntu machine and performs several linting tasks on the code in the repository, including:

- Checking out the code from the repository
- Setting up Python 3.11
- Installing a number of Python packages necessary for the linting tasks
- Running `codespell` to check the spelling of comments, strings, and variable names
- Running `black` to check the code formatting
- Running `ruff` to lint the code (replaces pylint, isort, flake8, and pydocstyle)
- Running `ty` to check the type annotations

The second job, `markdown-link-check`, runs on an Ubuntu machine and performs linting of the markdown files in the repository. It uses a Docker container `avtodev/markdown-lint` to perform the linting.

## 🏷️ Pull Request Labels

Validate that pull requests do not include the `do not merge` label.

## 🚉 Integration test Platform (API)

Run `openbb_platform` API integration tests,

## 🖥️ Unit test CLI

Run `cli` directory unit tests.

## 🚉 Unit test Platform

Run `openbb_platform` directory unit tests - providers, extensions, etc.
