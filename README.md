# AnduinOS 2

[![License](https://img.shields.io/badge/license-GPL-blue.svg)](https://github.com/AiursoftWeb/AnduinOS-2/blob/master/LICENSE)
[![Discussions](https://img.shields.io/badge/discussions-join-blue)](https://github.com/Anduin2017/AnduinOS/discussions)
[![Revolt Community](https://img.shields.io/badge/Revolt-Join-fd6671?style=flat-square)](https://rvlt.gg/dPwPs8e6)
[![Website](https://img.shields.io/website?url=https%3A%2F%2Fwww.anduinos.com%2F)](https://www.anduinos.com/)
[![Man Hours](https://manhours.aiursoft.com/r/github.com/aiursoftweb/anduinos-2.svg)](https://manhours.aiursoft.com/r/github.com/aiursoftweb/anduinos-2.html)

<p align="center">
  <img src="./logo.svg" alt="AnduinOS logo" width="120">
</p>

<p align="center">
  <strong>A familiar, modern, and easy-to-use Linux experience.</strong>
</p>

<p align="center">
  <a href="https://www.anduinos.com/">Website</a> •
  <a href="https://docs.anduinos.com/">Documentation</a> •
  <a href="https://github.com/Anduin2017/AnduinOS/discussions">Discussions</a> •
  <a href="https://github.com/Anduin2017/AnduinOS/issues">Issues</a>
</p>

---

## About

**AnduinOS** is a custom Ubuntu-based Linux distribution designed to provide a familiar, polished, and approachable desktop experience for users moving to Linux.

AnduinOS focuses on making Linux easier to understand and use without sacrificing the flexibility and openness of the Linux ecosystem.

The project includes its own build system, desktop configuration, installer integration, and curated open-source software stack.

> **AnduinOS 2** is the second-generation development line of AnduinOS.

If you are looking for the source code of **AnduinOS 1**, see the [AnduinOS 1 repository](https://github.com/anduin2017/anduinos).

## ✨ Highlights

* 🐧 Ubuntu-based Linux distribution
* 🖥️ Familiar and user-friendly desktop experience
* ⚙️ Reproducible ISO build system
* 📦 Curated open-source software ecosystem
* 🚀 Native AnduinOS installer integration
* 🧩 Modular configuration and build parameters
* 🧪 Designed for testing in virtual machines
* 🌐 Community-driven development and support

## 📸 Screenshot

![AnduinOS Desktop](./screenshot.png)

## ⬇️ Download

Ready to try AnduinOS?

**[Download AnduinOS](https://www.anduinos.com/)**

For documentation, installation instructions, and project information, visit:

**[AnduinOS Documentation](https://docs.anduinos.com/)**

---

# 🛠️ Building AnduinOS

The recommended build environment is **AnduinOS itself**.

Using AnduinOS as the build host helps keep the build environment aligned with the project's expected dependencies and configuration.

## Requirements

Before building, make sure you have:

* A working AnduinOS installation
* Sufficient disk space for the build environment
* A stable Internet connection
* Required build dependencies available on the system
* Permission to execute the project's build scripts

> Build requirements may change between releases. Check the project documentation and repository configuration before starting a production build.

## Build

Clone the repository:

```bash
git clone https://github.com/AiursoftWeb/AnduinOS-2.git
cd AnduinOS-2
```

Run the build system:

```bash
make
```

The resulting ISO image will be placed in:

```text
./dist/
```

You can then boot the generated ISO using either physical hardware or a virtual machine.

### ⚙️ Build Configuration

Build parameters are configured through:

```text
./args.sh
```

Edit this file when you need to customize the build configuration.

After changing the parameters, run:

```bash
make
```

again to generate a new ISO.

---

# 🧪 Testing

Before installing an image on physical hardware, testing the generated ISO inside a virtual machine is strongly recommended.

Popular virtualization platforms include:

* VMware Workstation / Fusion
* VirtualBox
* QEMU / KVM
* Hyper-V

A typical testing workflow is:

```text
Build
  ↓
Generate ISO
  ↓
Boot ISO in VM
  ↓
Test desktop and installer
  ↓
Report issues
  ↓
Improve configuration
  ↓
Build again
```

Testing in a virtual machine provides a safer way to validate changes before deploying them to real hardware.

---

# 📦 Installer & Live Environment

AnduinOS 2 uses **`anduinos-installer-beta`**, AnduinOS's native declarative installer.

The live environment is powered by **Casper**.

The legacy **Ubiquity integration stack has been retired** and is not included, built, or maintained by AnduinOS.

This separation allows the installer and live environment to evolve independently while keeping the build system focused on the current AnduinOS architecture.

---

# 📚 Documentation

Complete documentation is available at:

**[docs.anduinos.com](https://docs.anduinos.com/)**

The documentation is the recommended place to find installation instructions, development information, configuration details, and other project-specific guidance.

---

# 🤝 Contributing

Contributions are welcome.

You can help AnduinOS by:

* Reporting bugs
* Suggesting improvements
* Improving documentation
* Testing new builds
* Submitting pull requests
* Participating in discussions
* Helping other community members

Before contributing, please review the repository's contribution guidelines and existing discussions/issues to avoid duplicate work.

---

# 💬 Community & Support

For questions, ideas, troubleshooting, and general community discussion:

**[Join AnduinOS Discussions](https://github.com/Anduin2017/AnduinOS/discussions)**

For bug reports and feature requests:

**[Open an Issue](https://github.com/Anduin2017/AnduinOS/issues)**

You can also join the AnduinOS community on Revolt:

**[Join the AnduinOS Revolt Community](https://rvlt.gg/dPwPs8e6)**

---

# ❤️ Support the Project

AnduinOS is funded through user donations.

If you find the project useful and would like to support its continued development, you can contribute through Ko-fi.

<a href="https://ko-fi.com/anduinxue/goal?g=0" target="_blank" title="Support AnduinOS on Ko-fi">
  <img
    height="36"
    src="https://storage.ko-fi.com/cdn/kofi3.png?v=3"
    alt="Support AnduinOS on Ko-fi"
  />
</a>

Every contribution helps support continued development, infrastructure, testing, and maintenance.

---

# 📄 License

AnduinOS is licensed under the **GNU General Public License**.

See the [LICENSE](./LICENSE) file for the complete license text.

The open-source software included with AnduinOS is distributed in the hope that it will be useful, but **WITHOUT ANY WARRANTY**, to the extent permitted by applicable law.

A complete list of open-source software included in AnduinOS is available in:

**[OSS.md](./OSS.md)**

---

# 🗺️ Roadmap

The project may explore additional capabilities in the future, including:

* WSL support
* Docker container support
* Layer-based OS variants
* WSL / Server / Pro / Lite / Home / Workstation editions
* LiberOS
* Customized APT sources and package overrides
* Customized kernel and kernel configuration

> Roadmap items are subject to change and should not be interpreted as guaranteed release features.

---

## 🌟 Why AnduinOS?

AnduinOS aims to make the transition to Linux less intimidating while preserving the power and flexibility that makes Linux valuable.

Whether you're discovering Linux for the first time, developing software, experimenting in a virtual machine, or looking for a comfortable everyday desktop, AnduinOS is designed to provide a straightforward starting point.

---

<p align="center">
  <strong>Built with Linux. Built for people.</strong>
</p>

<p align="center">
  <a href="https://www.anduinos.com/">Website</a> •
  <a href="https://docs.anduinos.com/">Documentation</a> •
  <a href="https://github.com/Anduin2017/AnduinOS/discussions">Community</a>
</p>
