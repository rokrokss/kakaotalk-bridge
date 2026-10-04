# Contributing

[README](README.md) · [Development](docs/development.md) · [Validation scope](docs/implementation.md)

Bug reports, documentation improvements, and reports from additional environments help make the project easier to run. For a larger change, open an issue to discuss the scope first.

## Report a problem

[Open an issue](https://github.com/rokrokss/kakaotalk-bridge/issues) with:

- Your host OS and architecture, and whether you use Lima.
- The project revision, redroid image, and KakaoTalk version when relevant.
- Steps to reproduce, expected behavior, and observed behavior.
- Relevant error messages or sanitized logs.

Remove tokens, account details, and private messages before sharing logs or screenshots. Use synthetic messages in reproduction examples. See [Security](docs/security.md) for data and credential boundaries.

For compatibility reports, state which steps you actually verified: image build, Android boot, secondary login, phone session continuity, message collection, or MCP client connection. Identify manual confirmations explicitly.

## Propose a change

Keep each pull request focused and explain the behavior it changes. Include the checks you ran and their results; distinguish fixture-based tests from checks with a real device or account.

Follow the [contribution guidelines](docs/development.md#contribution-guidelines) and run the relevant [local checks](docs/development.md#local-checks). Documentation and project-owned UI text use English. Preserve Korean literals used to recognize the supported KakaoTalk screen and multilingual test data.

For admin or OAuth changes, use the [local browser previews](docs/development.md#preview-the-web-console) to check forms and user-visible behavior without a real account. For installation or collection changes, keep [Validation scope](docs/implementation.md) accurate and document remaining limitations.
