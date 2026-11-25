# Pull Request the OpenBB Platform

## Description

- [ ] Summary of the change/ bug fix.
- [ ] Link # issue, if applicable.
- [ ] Screenshot of the feature or the bug before/after fix, if applicable.
- [ ] Relevant motivation and context.
- [ ] List any dependencies that are required for this change.

## How has this been tested?

- Please describe the tests that you ran to verify your changes.
- Please provide instructions so we can reproduce.
- Please also list any relevant details for your test configuration.

- [ ] Ensure all unit and integration tests pass.
- If you modified/added command(s):
  - [ ] Ensure the command(s) execute with the expected output.
    - [ ] API.
    - [ ] Python Interface.
  - [ ] If applicable, please add new tests for the command (see [CONTRIBUTING.md](/openbb_platform/CONTRIBUTING.md) to leverage semi-automated testing).
- If a new provider was introduced or a new fetcher was added to an existing provider:
  - [ ] Ensure the existing tests pass.
  - [ ] Ensure the new provider and/or fetcher is stable and usable.
  - [ ] If applicable, please add new tests for the provider and/or fetcher (see [CONTRIBUTING.md](/openbb_platform/CONTRIBUTING.md) to leverage semi-automated testing).
- If a new provider or extension was added:
  - [ ] Update the list of [Extensions](/openbb_platform/EXTENSIONS.md).
  - [ ] Update the list of [Providers](/openbb_platform/PROVIDERS.md).
  - [ ] If it's a community extension or provider, update the [integration tests GitHub Action workflow](/.github/workflows/platform-api-integration-test.yml).

## Checklist

- [ ] I have performed a self-review of my own code.
- [ ] I have commented my code, particularly in hard-to-understand areas.
- [ ] I have adhered to the GitFlow naming convention and my branch name is in the format of `feature/feature-name` or `hotfix/hotfix-name`.
- [ ] I ensure that I am following the [CONTRIBUTING guidelines](/openbb_platform/CONTRIBUTING.md).
  - [ ] (If applicable) I have updated tests following [these guidelines](/openbb_platform/CONTRIBUTING.md#qa-your-extension).

</details>
