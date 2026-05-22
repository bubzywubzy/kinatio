from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha3_256
from typing import Any, Literal

from kinatio.domain.models import SystemState

CollectionMode = Literal["eager", "defer_until_unlock"]
PayloadMode = Literal["subsystem", "combined", "events", "state"]


@dataclass(slots=True, frozen=True)
class CategoryPolicy:
    description: str
    sections: tuple[str, ...]


@dataclass(slots=True, frozen=True)
class SectionPolicy:
    description: str
    category: str
    subsystem: str | None = None
    requires_auth: bool = False
    collection_mode: CollectionMode = "eager"
    followable: bool = False
    payload_mode: PayloadMode = "subsystem"
    payload_subsystems: tuple[str, ...] = ()
    updated_at_subsystems: tuple[str, ...] = ()
    cli_visible: bool = True
    aliases: tuple[str, ...] = ()


CATEGORY_POLICIES: dict[str, CategoryPolicy] = {
    "Overview": CategoryPolicy(
        description="Global host summary and alert-oriented landing view.",
        sections=("Overview",),
    ),
    "Health": CategoryPolicy(
        description="Core host health, capacity, and performance signals.",
        sections=("System Health", "Hardware", "Performance", "Storage", "Power"),
    ),
    "Operations": CategoryPolicy(
        description="Running workloads, active units, sessions, and recent events.",
        sections=("Processes", "Services", "Containers", "Sessions", "Events"),
    ),
    "Network": CategoryPolicy(
        description="Connectivity, routing, ports, and firewall posture.",
        sections=("Network Summary", "Interfaces", "Routes & DNS", "Ports & Connections", "Firewall"),
    ),
    "Security": CategoryPolicy(
        description="Security findings, privileged posture, and audit coverage.",
        sections=("Security Posture", "Access & Identity", "Exposure", "Audit"),
    ),
    "Administration": CategoryPolicy(
        description="Kernel, package, and log visibility for system administration.",
        sections=("System", "Kernel", "Packages", "Logs", "Runtime Backends"),
    ),
}


SECTION_POLICIES: dict[str, SectionPolicy] = {
    "Overview": SectionPolicy(
        description="High-level host summary composed from current operational counts and health signals.",
        category="Overview",
        payload_mode="combined",
        payload_subsystems=(
            "hardware",
            "os_state",
            "processes",
            "services",
            "security",
            "network",
            "storage",
            "packages",
            "containers",
            "sessions",
            "audit",
            "runtime",
        ),
        updated_at_subsystems=(
            "hardware",
            "os_state",
            "processes",
            "services",
            "security",
            "network",
            "storage",
            "packages",
            "containers",
            "sessions",
            "audit",
            "runtime",
        ),
    ),
    "System Health": SectionPolicy(
        description="Host health summary focused on identity, load, memory pressure, and backend readiness.",
        category="Health",
        subsystem="os_state",
        payload_mode="combined",
        payload_subsystems=("hardware", "os_state", "runtime", "processes", "services"),
        updated_at_subsystems=("hardware", "os_state", "runtime", "processes", "services"),
        cli_visible=False,
    ),
    "System": SectionPolicy(
        description="Host identity, uptime, load, and runtime backend context.",
        category="Administration",
        subsystem="os_state",
        payload_mode="combined",
        payload_subsystems=("os_state", "runtime"),
        updated_at_subsystems=("os_state", "runtime"),
    ),
    "Hardware": SectionPolicy(
        description="Physical hardware overview across CPU, memory, graphics, thermals, and storage-device summaries.",
        category="Health",
        subsystem="hardware",
        updated_at_subsystems=("hardware", "power", "storage"),
    ),
    "Performance": SectionPolicy(
        description="Derived performance view across CPU, load, memory, and processes.",
        category="Health",
        payload_mode="combined",
        payload_subsystems=("hardware", "os_state", "processes"),
        updated_at_subsystems=("hardware", "os_state", "processes"),
    ),
    "Network": SectionPolicy(
        description="Interfaces, routes, DNS, connections, and firewall status.",
        category="Network",
        subsystem="network",
    ),
    "Network Summary": SectionPolicy(
        description="Concise connectivity overview across interfaces, routes, DNS, and firewall state.",
        category="Network",
        subsystem="network",
        payload_mode="combined",
        payload_subsystems=("network", "runtime"),
        updated_at_subsystems=("network", "runtime"),
        cli_visible=False,
    ),
    "Interfaces": SectionPolicy(
        description="Interactive interface inventory with per-link detail drill-in.",
        category="Network",
        subsystem="network",
        cli_visible=False,
    ),
    "Routes & DNS": SectionPolicy(
        description="Focused routing and resolver view without interface traffic noise.",
        category="Network",
        subsystem="network",
        cli_visible=False,
    ),
    "Ports & Connections": SectionPolicy(
        description="Listening socket and active connection visibility for exposed network activity.",
        category="Network",
        subsystem="network",
        cli_visible=False,
    ),
    "Firewall": SectionPolicy(
        description="Firewall backend, availability, and policy summary.",
        category="Network",
        subsystem="network",
        payload_mode="combined",
        payload_subsystems=("network", "runtime"),
        updated_at_subsystems=("network", "runtime"),
        cli_visible=True,
    ),
    "Processes": SectionPolicy(
        description="Top process inventory and current resource usage.",
        category="Operations",
        subsystem="processes",
    ),
    "Services": SectionPolicy(
        description="Service-manager inventory from the detected backend.",
        category="Operations",
        subsystem="services",
    ),
    "Storage": SectionPolicy(
        description="Mounts, per-disk detail, SMART health, temperatures, and storage counters.",
        category="Health",
        subsystem="storage",
    ),
    "Logs": SectionPolicy(
        description="Recent logs and live follow support from the detected log backend.",
        category="Administration",
        subsystem="logs",
        requires_auth=True,
        collection_mode="defer_until_unlock",
        followable=True,
    ),
    "Security": SectionPolicy(
        description="Bounded posture sampler for sudo state, users, groups, and anomalies.",
        category="Security",
        subsystem="security",
        requires_auth=True,
        collection_mode="defer_until_unlock",
    ),
    "Security Posture": SectionPolicy(
        description="High-level security posture focused on findings, sudo state, and privileged access health.",
        category="Security",
        subsystem="security",
        requires_auth=True,
        collection_mode="defer_until_unlock",
        cli_visible=False,
    ),
    "Access & Identity": SectionPolicy(
        description="Users, groups, and sudo configuration details separated from broader posture findings.",
        category="Security",
        subsystem="security",
        requires_auth=True,
        collection_mode="defer_until_unlock",
        cli_visible=False,
    ),
    "Exposure": SectionPolicy(
        description="Externally exposed services and risk-oriented findings that warrant follow-up.",
        category="Security",
        subsystem="security",
        requires_auth=True,
        collection_mode="defer_until_unlock",
        cli_visible=False,
    ),
    "Sessions": SectionPolicy(
        description="Current sessions and recent login summaries.",
        category="Operations",
        subsystem="sessions",
    ),
    "Power": SectionPolicy(
        description="Battery, thermal, fan, and governor telemetry with detailed sensor visibility when exposed.",
        category="Health",
        subsystem="power",
    ),
    "Kernel": SectionPolicy(
        description="Focused kernel release, version, and sampled sysctl view.",
        category="Administration",
        subsystem="os_state",
    ),
    "Packages": SectionPolicy(
        description="Installed package sample and update count summaries.",
        category="Administration",
        subsystem="packages",
    ),
    "Runtime Backends": SectionPolicy(
        description="Detected distro and backend integrations used by service, logs, firewall, security, and containers.",
        category="Administration",
        subsystem="runtime",
        payload_mode="combined",
        payload_subsystems=("runtime", "services", "logs", "packages", "network", "audit", "containers"),
        updated_at_subsystems=("runtime", "services", "logs", "packages", "network", "audit", "containers"),
        cli_visible=False,
    ),
    "Audit": SectionPolicy(
        description="SELinux, AppArmor, auditd, and auditctl posture summaries.",
        category="Security",
        subsystem="audit",
        requires_auth=True,
        collection_mode="defer_until_unlock",
    ),
    "Containers": SectionPolicy(
        description="Container runtime inventory and image counts.",
        category="Operations",
        subsystem="containers",
    ),
    "Events": SectionPolicy(
        description="Recent collector and action events from the state store.",
        category="Operations",
        payload_mode="events",
    ),
}

_declared_category_sections = {
    section
    for category_policy in CATEGORY_POLICIES.values()
    for section in category_policy.sections
}
unknown_sections = sorted(_declared_category_sections - set(SECTION_POLICIES))
misaligned_sections = sorted(
    section
    for section in _declared_category_sections
    if SECTION_POLICIES[section].category != next(
        category
        for category, category_policy in CATEGORY_POLICIES.items()
        if section in category_policy.sections
    )
)
if unknown_sections or misaligned_sections:
    raise RuntimeError(
        "category section definitions must resolve to known section policies: "
        f"unknown={unknown_sections!r} misaligned={misaligned_sections!r}"
    )

SECTIONS = [
    section for section, policy in SECTION_POLICIES.items() if policy.cli_visible
]
TOP_LEVEL_CATEGORIES = list(CATEGORY_POLICIES)
SECTION_COMMANDS = {
    alias: section
    for section, policy in SECTION_POLICIES.items()
    if policy.cli_visible
    for alias in (section.lower(), *policy.aliases)
}
SECTION_DESCRIPTIONS = {
    section: policy.description for section, policy in SECTION_POLICIES.items()
}
FOLLOWABLE_SECTIONS = {
    section for section, policy in SECTION_POLICIES.items() if policy.followable
}
PRIVILEGED_SECTIONS = {
    section for section, policy in SECTION_POLICIES.items() if policy.requires_auth
}
DEFERRED_SUBSYSTEMS = {
    policy.subsystem
    for policy in SECTION_POLICIES.values()
    if policy.requires_auth
    and policy.collection_mode == "defer_until_unlock"
    and policy.subsystem is not None
}
SECTION_CATEGORY = {
    section: policy.category for section, policy in SECTION_POLICIES.items()
}
DEFAULT_SECTION_BY_CATEGORY = {
    category: policy.sections[0] for category, policy in CATEGORY_POLICIES.items()
}

CATEGORY_ICONS: dict[str, str] = {
    "Overview": "OV",
    "Health": "HL",
    "Operations": "OP",
    "Network": "NW",
    "Security": "SC",
    "Administration": "AD",
}

SECTION_ICONS: dict[str, str] = {
    "Overview": "OV",
    "System Health": "SH",
    "System": "SY",
    "Hardware": "HW",
    "Performance": "PF",
    "Network": "NW",
    "Network Summary": "NS",
    "Interfaces": "IF",
    "Routes & DNS": "RD",
    "Ports & Connections": "PC",
    "Firewall": "FW",
    "Processes": "PR",
    "Services": "SV",
    "Storage": "ST",
    "Logs": "LG",
    "Security": "SC",
    "Security Posture": "SP",
    "Access & Identity": "AI",
    "Exposure": "EX",
    "Sessions": "SS",
    "Power": "PW",
    "Kernel": "KR",
    "Packages": "PK",
    "Runtime Backends": "RB",
    "Audit": "AU",
    "Containers": "CT",
    "Events": "EV",
}


def get_category_policy(category: str) -> CategoryPolicy | None:
    return CATEGORY_POLICIES.get(category)


def get_category_sections(category: str) -> tuple[str, ...]:
    policy = get_category_policy(category)
    if policy is None:
        return ()
    return policy.sections


def get_default_section(category: str) -> str | None:
    return DEFAULT_SECTION_BY_CATEGORY.get(category)


def get_category_icon(category: str) -> str:
    return CATEGORY_ICONS.get(category, category[:2].upper())


def get_section_icon(section: str) -> str:
    return SECTION_ICONS.get(section, section[:2].upper())


def get_section_category(section: str) -> str | None:
    return SECTION_CATEGORY.get(section)


def get_tui_visible_section(section: str) -> str:
    category = get_section_category(section)
    if category is None:
        return section
    category_sections = get_category_sections(category)
    if section in category_sections:
        return section
    if category_sections:
        return category_sections[0]
    return section


def get_section_policy(section: str) -> SectionPolicy | None:
    return SECTION_POLICIES.get(section)


def section_payload_data(section: str, state: SystemState) -> Any:
    policy = get_section_policy(section)
    if policy is None:
        return state.model_dump(mode="json")
    if policy.payload_mode == "events":
        return [event.model_dump(mode="json") for event in state.events]
    if policy.payload_mode == "combined":
        return {
            subsystem: getattr(state, subsystem).model_dump(mode="json")
            for subsystem in policy.payload_subsystems
        }
    if policy.payload_mode == "subsystem" and policy.subsystem is not None:
        return getattr(state, policy.subsystem).model_dump(mode="json")
    return state.model_dump(mode="json")


def section_payload_signature(section: str, state: SystemState) -> str:
    return sha3_256(repr(section_payload_data(section, state)).encode("utf-8")).hexdigest()


def section_updated_at(section: str, state: SystemState) -> datetime:
    policy = get_section_policy(section)
    if policy is None:
        return state.timestamp
    if policy.payload_mode == "events":
        return state.events[-1].timestamp if state.events else state.timestamp
    subsystems = policy.updated_at_subsystems or policy.payload_subsystems
    if not subsystems and policy.subsystem is not None:
        subsystems = (policy.subsystem,)
    if not subsystems:
        return state.timestamp
    refreshed_times = [
        getattr(getattr(state, subsystem, None), "refreshed_at", state.timestamp)
        for subsystem in subsystems
    ]
    return max(refreshed_times) if refreshed_times else state.timestamp
