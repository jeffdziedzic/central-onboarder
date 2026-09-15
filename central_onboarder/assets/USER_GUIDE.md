# Central Onboarder - User Guide

This is not an official tool. It was built around a single environment's
onboarding workflow by an amateur coder. Use at your own risk.

## Status

v0.1.0 is a fresh scaffold. Nothing in this tool has been exercised
against a real GLCP/New Central/Classic Central tenant yet - every API
call it makes was ported from a sibling project (the AOS8-to-AOS10
Conversion Tool) where the endpoint/body shape WAS live-confirmed, but
that confirmation doesn't carry over automatically to this tool's own
first real run. Treat every screen as unverified until you've clicked
it against a real tenant and it did what you expected. In particular:

- "Assign Service" (Central application assignment) auto-discovers the
  application ID from another already-assigned device in your
  workspace - this only works if your workspace already has at least
  one device assigned to Central. A brand-new/empty workspace, or
  assigning a different application (e.g. UXI, not yet built), needs an
  explicit application ID.
- Site assignment goes through Classic Central's site-association API
  even for New-Central-managed devices, mirroring what the sibling
  conversion project found actually works live. If your tenant is
  fully migrated off Classic Central, this may need revisiting.
- UXI sensor onboarding is not built yet (see Assumptions below).

## Assumptions and limitations

- Onboards APs, switches, and gateways. UXI sensors are a planned
  future addition (they sit in GLCP under their own UXI application,
  not Central) - not available in this version.
- Windows/macOS packaging (a standalone .exe/.app) hasn't been built
  yet - run this from a Python checkout (see the repo's README).
- No CLI - the GUI is the only front end.

## Before you start

- **Credentials**: this tool needs a New Central API client
  (client_credentials grant - also used for GLCP calls, no separate
  GLCP credential needed) and, for group pre-provisioning and site
  assignment, a Classic Central API client (refresh_token grant). See
  the Credentials screen's "How do I get this?" links.
- **Device list**: a single working Excel file tracks every device
  you're onboarding - its columns are Serial, MAC, Device Type, Target
  Group, Target Site, Subscription Key, plus tracking columns this tool
  fills in as you complete each step. Import a CSV or add devices
  manually from the Device List screen.

## Screens

1. **Credentials** - store your New Central and Classic Central API
   clients. Test checks a credential without writing anything.
2. **Device List** - set your working device-list file, import a CSV,
   or add/edit devices manually.
3. **Onboard** - for selected devices: add to GLCP, assign a
   subscription, assign the Central service (application).
4. **Pre-Provision** - assign selected devices to a Classic Central
   group, ahead of (or after) their first check-in.
5. **Assign Site** - once a device has actually checked into Central,
   assign it to a New Central site. This is a manual step you run when
   you know devices are online, not an automatic background poll.
6. **Tools** - create a New Central site.
