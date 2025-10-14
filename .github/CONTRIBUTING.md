# Contributing guidelines

Raise a PR.

## Conventional Commits

This project follows [Conventional Commits 1.0.0](https://www.conventionalcommits.org/en/v1.0.0/) specification to create a clear and explicit commit history.

```text
<type>[optional scope]: <short description>

[optional body]

[optional footer]
```

- `MAJOR` Semantic Versioning are triggered by appending a **!** after the **type/scope**, or a commit that has a footer **BREAKING CHANGE:**.
- `MINOR` Semantic Versioning are triggered by using the **feat** type to indicate a new feature introduction to the codebase
- `PATCH` Semantic Versioning are triggered by using the **fix** type to indicate a bugfix to the codebase.
- **Others types** are of no Semantic Versionin impact as following:
  - **build** for code changes impacting the local build process
  - **bump** for releasing the code
  - **chore** for on-going recurring activities (i.e.: dependencies update)
  - **ci** for code changes impacting the CI build process
  - **docs** for documentation changes
  - **perf** for performance improvement that does not change the code behavior
  - **refactor** for refactoring code without changing the code behavior
  - **revert** for revert code changes if required
  - **style** for style and lint the current code base
  - **test** for code changes impacting the test suites for this codebase
