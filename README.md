# CAN Bus Intrusion Detection System

A timing-based intrusion detection system for in-vehicle **CAN bus**
(Controller Area Network) traffic — the communication protocol used by
virtually every modern vehicle's ECUs (engine, brakes, airbags,
infotainment) to exchange messages. Automotive CAN security is a
well-documented real-world concern: the 2015 Jeep Cherokee remote hack
(Miller & Valasek) demonstrated exactly this attack surface, remotely
controlling steering and braking via injected CAN messages.

## Core insight

Legitimate CAN messages are **periodic** — each ECU broadcasts its message
(engine RPM, wheel speed, brake status, etc.) at a fixed interval, typically
10–1000ms depending on the signal's criticality. This regularity is exactly
what attacks disrupt, and exactly what this project exploits for detection.

Three attack types are simulated:
- **DoS/flooding** — an attacker floods the bus with high-priority messages
  to starve legitimate traffic.
- **Spoofing/injection** — fake messages sent using a legitimate CAN ID
  (e.g. forged brake commands), breaking that ID's normal timing.
- **Replay** — previously captured legitimate messages replayed rapidly,
  out of their normal timing context.

## Two detection methods, honestly compared

This project implements and evaluates **two different approaches**, and —
importantly — reports the real, tested results for both, including where
one method clearly outperforms the other and why.

### Method 1: Per-CAN-ID statistical timing baseline

Learns the normal inter-arrival time (mean, standard deviation) for each
CAN ID individually, then flags messages whose timing deviates beyond a
z-score threshold. This mirrors real automotive IDS research, which
frequently uses per-ID timing baselines precisely because CAN traffic is
so mechanically regular that deviations are an unusually strong, low
false-positive signal.

### Method 2: Isolation Forest (unsupervised ML)

A general-purpose anomaly detector trained only on timing/frequency
features, without using any attack labels — relevant because in practice,
truly novel attacks won't match a known signature.

## Results (tested on 21,100 simulated CAN messages, ~48% attack traffic)

| Method | Accuracy | Notes |
|---|---|---|
| **Per-ID timing baseline** | **~100%** | Near-perfect: 10,120/10,120 attacks caught, only 19 false positives out of 10,980 normal messages |
| **Isolation Forest** | **~57%** | Substantially weaker, even after feature engineering and contamination tuning |

### Why the gap? (an honest finding, not a shortcoming to hide)

Initial Isolation Forest testing performed even worse (~45%) using a
**global** local-message-rate feature. Investigation showed the problem:
during the simulated DoS flood, *normal* messages that happened to occur
in the same time window also received inflated rate values, since the
feature counted nearby messages of any CAN ID — conflating attack traffic
with unrelated concurrent normal traffic.

Switching to a **per-CAN-ID** local rate feature and properly scaling
inputs improved results (45% → 57%), but Isolation Forest still
substantially underperforms the domain-specific timing baseline. This
makes sense: CAN bus traffic is unusually structured and regular compared
to the general-purpose data Isolation Forest is typically applied to. A
method that explicitly models each ID's expected periodicity has a much
stronger, more specific signal to work with than a generic
distance-based anomaly detector operating on aggregate features.

**Practical takeaway:** for highly structured, periodic protocols like CAN,
a domain-informed statistical method can meaningfully outperform an
off-the-shelf general anomaly detector — worth knowing before defaulting
to "throw ML at it."

## Installation

```bash
git clone https://github.com/aya-hassen/can-ids.git
cd can-ids
pip install -r requirements.txt
```

## Usage

```bash
# 1. Simulate CAN bus traffic (normal + injected attacks)
python3 generate_can_traffic.py --duration 60 --output can_traffic.csv

# 2. Run both detection methods and evaluate
python3 detect_anomalies.py --input can_traffic.csv
```

## Project structure

```
can-ids/
├── generate_can_traffic.py   # CAN bus traffic simulator (normal + 3 attack types)
├── detect_anomalies.py        # both detection methods + evaluation
├── requirements.txt
└── README.md
```

## Limitations & honest caveats

- **Simulated traffic, not a real vehicle CAN capture.** The message set
  and timing parameters are illustrative, modeled on documented real ECU
  behavior, but a real deployment needs validation against genuine vehicle
  bus captures.
- **Ground-truth labels used to build the timing baseline**, which
  wouldn't be available in a fully unsupervised real deployment — a
  production system would need to learn the baseline from a trusted
  traffic window instead.
- **Isolation Forest's weaker performance here is specific to this
  highly-regular protocol** — it may perform comparatively better on
  less structured anomaly detection problems (as seen in this author's
  separate `network-ids` project, applied to general network traffic).

## Possible extensions

- Test against real CAN bus datasets (e.g. the Car Hacking Dataset from
  the Hacking and Countermeasure Research Lab, HCRL).
- Add a supervised classifier (e.g. Random Forest) trained on the same
  features, to compare against both unsupervised approaches.
- Extend attack simulation to include more subtle injection patterns that
  partially mimic legitimate timing.

## Author

Aya Hassen — Computer Science undergraduate, Constructor University Bremen.
Built as part of ongoing work exploring the intersection of cybersecurity,
machine learning, and automotive systems.
