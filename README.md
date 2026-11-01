<br />
<img src="https://github.com/OpenBB-finance/OpenBB/blob/develop/images/odp-light.svg?raw=true#gh-light-mode-only" alt="Open Data Platform by OpenBB logo" width="600">
<img src="https://github.com/OpenBB-finance/OpenBB/blob/develop/images/odp-dark.svg?raw=true#gh-dark-mode-only" alt="Open Data Platform by OpenBB logo" width="600">
<br />
<br />

[![Twitter](https://img.shields.io/twitter/url/https/twitter.com/openbb_finance.svg?style=social&label=Follow%20%40openbb_finance)](https://x.com/openbb_finance)
[![Discord Shield](https://img.shields.io/discord/831165782750789672)](https://discord.com/invite/xPHTuHCmuV)
[![Open in Dev Containers](https://img.shields.io/static/v1?label=Dev%20Containers&message=Open&color=blue&logo=visualstudiocode)](https://vscode.dev/redirect?url=vscode://ms-vscode-remote.remote-containers/cloneInVolume?url=https://github.com/OpenBB-finance/OpenBB)
<a href="https://codespaces.new/OpenBB-finance/OpenBB">
  <img src="https://github.com/codespaces/badge.svg" height="20" />
</a>
<a target="_blank" href="https://colab.research.google.com/github/OpenBB-finance/OpenBB/blob/develop/examples/googleColab.ipynb">
  <img src="https://colab.research.google.com/assets/colab-badge.svg" alt="Open In Colab"/>
</a>
[![PyPI](https://img.shields.io/pypi/v/openbb?color=blue&label=PyPI%20Package)](https://pypi.org/project/openbb/)

Open Data Platform by OpenBB (ODP) is the open-source toolset that helps data engineers integrate proprietary, licensed, and public data sources into downstream applications like AI copilots and research dashboards.

ODP operates as the "connect once, consume everywhere" infrastructure layer that consolidates and exposes data to multiple surfaces at once: Python environments for quants, OpenBB Workspace and Excel for analysts, MCP servers for AI agents, and REST APIs for other applications.

<a href="https://pro.openbb.co">
  <div align="center">
  <img src="https://openbb-cms.directus.app/assets/70b971ef-7a7e-486e-b5ae-1cc602f2162c.png" alt="Logo" width="1000">
  </div>
</a>

Get started with: `pip install openbb`

```python
from openbb import obb
output = obb.equity.price.historical("AAPL")
df = output.to_dataframe()
```

Data integrations available can be found here: [OpenBB Python Reference](https://docs.openbb.co/python/reference)

---

## OpenBB Workspace

While the Open Data Platform provides the open-source data integration foundation, **OpenBB Workspace** offers the enterprise UI for analysts to visualize datasets and leverage AI agents. The platform's "connect once, consume everywhere" architecture enables seamless integration between the two.

You can find OpenBB Workspace at [pro.openbb.co](https://pro.openbb.co).
<a href="https://pro.openbb.co">
  <div align="center">
  <img src="https://openbb-cms.directus.app/assets/f69b6aaf-0821-4bc8-a43c-715e03a924ef.png" alt="Logo" width="1000">
  </div>
</a>

Data integration:

- You can learn more about adding data to the OpenBB workspace from the [docs](https://docs.openbb.co/workspace) or [this open source repository](https://github.com/OpenBB-finance/backends-for-openbb).

AI Agents integration:

- You can learn more about adding AI agents to the OpenBB workspace from [this open source repository](https://github.com/OpenBB-finance/agents-for-openbb).

### Integrating Open Data Platform to the OpenBB Workspace

Connect this library to the OpenBB Workspace with a few simple commands, in a Python (3.10 - 3.14) environment.

#### Run an ODP backend

- Install the packages.

```sh
pip install openbb
```

- Start the API server over localhost.

```sh
openbb-api
```

This will launch a FastAPI server, via Uvicorn, at `127.0.0.1:6900`.

You can check that it works by going to [`http://127.0.0.1:6900`](http://127.0.0.1:6900).

#### Integrate the ODP Backend to OpenBB Workspace

Sign-in to the [OpenBB Workspace](https://pro.openbb.co/), and follow the following steps:

![CleanShot 2025-05-17 at 09 51 56@2x](https://github.com/user-attachments/assets/75cffb4a-5e95-470a-b9d0-6ffd4067e069)

1. Go to the "Apps" tab
2. Click on "Connect backend"
3. Fill in the form with:
   Name: Open Data Platform
   URL: [`http://127.0.0.1:6900`](http://127.0.0.1:6900)
4. Click on "Test". You should get a "Test successful" with the number of apps found.
5. Click on "Add".

That's it.

---

<!-- TABLE OF CONTENTS -->
<details closed="closed">
  <summary><h2 style="display: inline-block">Table of Contents</h2></summary>
  <ol>
    <li><a href="#1-installation">Installation</a></li>
    <li><a href="#2-contributing">Contributing</a></li>
    <li><a href="#3-license">License</a></li>
    <li><a href="#4-disclaimer">Disclaimer</a></li>
    <li><a href="#5-contacts">Contacts</a></li>
    <li><a href="#6-star-history">Star History</a></li>
    <li><a href="#7-contributors">Contributors</a></li>
  </ol>
</details>

## 1. Installation

The ODP Python Package can be installed from [PyPI package](https://pypi.org/project/openbb/) by running `pip install openbb`

or by cloning the repository directly with `git clone https://github.com/OpenBB-finance/OpenBB.git`.

Please find more about the installation process, in the [OpenBB Documentation](https://docs.openbb.co/python/installation).

### ODP CLI installation

The ODP CLI is a command-line interface that allows you to access the ODP directly from your command line.

It can be installed by running `pip install openbb-cli`

or by cloning the repository directly with  `git clone https://github.com/OpenBB-finance/OpenBB.git`.

Please find more about the installation process in the [OpenBB Documentation](https://docs.openbb.co/cli/installation).

## 2. Contributing

There are three main ways of contributing to this project. (Hopefully you have starred the project by now ⭐️)

### Become a Contributor

- More information on our [Developer Documentation](https://docs.openbb.co/python/developer).

### Create a GitHub ticket

Before creating a ticket make sure the one you are creating doesn't exist already [among the existing issues](https://github.com/OpenBB-finance/OpenBB/issues)

- [Report bug](https://github.com/OpenBB-finance/OpenBB/issues/new?assignees=&labels=bug&template=bug_report.md&title=%5BBug%5D)
- [Suggest improvement](https://github.com/OpenBB-finance/OpenBB/issues/new?assignees=&labels=enhancement&template=enhancement.md&title=%5BIMPROVE%5D)
- [Request a feature](https://github.com/OpenBB-finance/OpenBB/issues/new?assignees=&labels=new+feature&template=feature_request.md&title=%5BFR%5D)

### Provide feedback

We are most active on [our Discord](https://openbb.co/discord), but feel free to reach out to us in any of [our social media](https://openbb.co/links) for feedback.

## 3. License

Distributed under the Apache License, Version 2.0. See
[LICENSE](https://github.com/OpenBB-finance/OpenBB/blob/main/LICENSE) for more information.

## 4. Disclaimer

Trading in financial instruments involves high risks including the risk of losing some, or all, of your investment
amount, and may not be suitable for all investors.

Before deciding to trade in a financial instrument you should be fully informed of the risks and costs associated with trading the financial markets, carefully consider your investment objectives, level of experience, and risk appetite, and seek professional advice where needed.

The data contained in the Open Data Platform is not necessarily accurate.

OpenBB and any provider of the data contained in this website will not accept liability for any loss or damage as a result of your trading, or your reliance on the information displayed.

All names, logos, and brands of third parties that may be referenced in our sites, products or documentation are trademarks of their respective owners. Unless otherwise specified, OpenBB and its products and services are not endorsed by, sponsored by, or affiliated with these third parties.

Our use of these names, logos, and brands is for identification purposes only, and does not imply any such endorsement, sponsorship, or affiliation.

## 5. Contacts

If you have any questions about the platform or anything OpenBB, feel free to email us at [support@openbb.co](mailto:support@openbb.co)

If you want to say hi, or are interested in partnering with us, feel free to reach us at [hello@openbb.co](mailto:hello@openbb.co)

Any of our social media platforms: [openbb.co/links](https://openbb.co/links)

## 6. Star History

This is a proxy of our growth and that we are just getting started.

But for more metrics important to us check [OpenBB Open](https://openbb.co/open).

[![Star History Chart](https://api.star-history.com/svg?repos=openbb-finance/OpenBB&type=Date&theme=dark)](https://api.star-history.com/svg?repos=openbb-finance/OpenBB&type=Date&theme=dark)

## 7. Contributors

OpenBB wouldn't be OpenBB without you. If we are going to disrupt financial industry, every contribution counts. Thank you for being part of this journey.

<a href="https://github.com/OpenBB-finance/OpenBB/graphs/contributors">
   <img src="https://contributors-img.web.app/image?repo=OpenBB-finance/OpenBB" width="800"/>
</a>

<!-- MARKDOWN LINKS & IMAGES -->
<!-- https://www.markdownguide.org/basic-syntax/#reference-style-links -->

[contributors-shield]: https://img.shields.io/github/contributors/OpenBB-finance/OpenBB.svg?style=for-the-badge
[contributors-url]: https://github.com/OpenBB-finance/OpenBB/graphs/contributors
[forks-shield]: https://img.shields.io/github/forks/OpenBB-finance/OpenBB.svg?style=for-the-badge
[forks-url]: https://github.com/OpenBB-finance/OpenBB/network/members
[stars-shield]: https://img.shields.io/github/stars/OpenBB-finance/OpenBB.svg?style=for-the-badge
[stars-url]: https://github.com/OpenBB-finance/OpenBB/stargazers
[issues-shield]: https://img.shields.io/github/issues/OpenBB-finance/OpenBB.svg?style=for-the-badge&color=blue
[issues-url]: https://github.com/OpenBB-finance/OpenBB/issues
[bugs-open-shield]: https://img.shields.io/github/issues/OpenBB-finance/OpenBB/bug.svg?style=for-the-badge&color=yellow
[bugs-open-url]: https://github.com/OpenBB-finance/OpenBB/issues?q=is%3Aissue+label%3Abug+is%3Aopen
[bugs-closed-shield]: https://img.shields.io/github/issues-closed/OpenBB-finance/OpenBB/bug.svg?style=for-the-badge&color=success
[bugs-closed-url]: https://github.com/OpenBB-finance/OpenBB/issues?q=is%3Aissue+label%3Abug+is%3Aclosed
[license-shield]: https://img.shields.io/github/license/OpenBB-finance/OpenBB.svg?style=for-the-badge
[license-url]: https://github.com/OpenBB-finance/OpenBB/blob/main/LICENSE.txt
[linkedin-shield]: https://img.shields.io/badge/-LinkedIn-black.svg?style=for-the-badge&logo=linkedin&colorB=555
[linkedin-url]: https://linkedin.com/in/DidierRLopes
