from mergexp import *

# =============================================================================
# SPHERE-EC-POMDG
# Paper-grade virtual / hybrid-ready smart-grid cyber-deception testbed.
#
# Design rules:
#   1. Experiment traffic uses only the explicitly assigned experiment networks.
#   2. SPHERE infranet is reserved for XDC/SSH/Ansible orchestration only.
#   3. The decoy is never connected to the physical-process network.
#   4. Process, telemetry, and defense planes are layer-2-only so Merge does
#      not automatically add production-network routes into those planes.
#   5. The collector/broker relays observations/actions at the application
#      layer; it must NOT enable IP forwarding between telemetry and defense.
# =============================================================================

net = Network(
    "sphere-ecpomdg-powergrid",
    routing == static,
)

# -----------------------------------------------------------------------------
# Nodes
# -----------------------------------------------------------------------------

attacker = net.node(
    "attacker",
    image == "2404",
    proc.cores >= 2,
    memory.capacity >= gb(2),
)

edgegw = net.node(
    "edgegw",
    image == "2404",
    proc.cores >= 1,
    memory.capacity >= gb(1),
)

scada = net.node(
    "scada",
    image == "2404",
    proc.cores >= 2,
    memory.capacity >= gb(2),
)

historian = net.node(
    "historian",
    image == "2404",
    proc.cores >= 2,
    memory.capacity >= gb(4),
    rootfs.capacity == gb(64),
)

fieldgw = net.node(
    "fieldgw",
    image == "2404",
    proc.cores >= 1,
    memory.capacity >= gb(1),
)

controller = net.node(
    "controller",
    image == "2404",
    proc.cores >= 2,
    memory.capacity >= gb(2),
)

decoy = net.node(
    "decoy",
    image == "2404",
    proc.cores >= 2,
    memory.capacity >= gb(2),
)

gridsim = net.node(
    "gridsim",
    image == "2404",
    proc.cores >= 4,
    memory.capacity >= gb(8),
    rootfs.capacity == gb(64),
)

collector = net.node(
    "collector",
    image == "2404",
    proc.cores >= 2,
    memory.capacity >= gb(4),
    rootfs.capacity == gb(128),
)

kg = net.node(
    "kg",
    image == "2404",
    proc.cores >= 4,
    memory.capacity >= gb(8),
    rootfs.capacity == gb(64),
)

defender = net.node(
    "defender",
    image == "2404",
    proc.cores >= 4,
    memory.capacity >= gb(8),
    rootfs.capacity == gb(64),
)

operator = net.node(
    "operator",
    image == "2404",
    proc.cores >= 2,
    memory.capacity >= gb(2),
)

# Expose only the human/operator dashboard.
# The service should later bind to 0.0.0.0:8501 because SPHERE ingress
# arrives over the node's infranet interface.
operator.ingress(http, 8501)

# -----------------------------------------------------------------------------
# Ansible groups
# -----------------------------------------------------------------------------

attacker.properties["group"] = ["attack"]
edgegw.properties["group"] = ["gateways"]
scada.properties["group"] = ["control_center"]
historian.properties["group"] = ["control_center"]
fieldgw.properties["group"] = ["gateways"]
controller.properties["group"] = ["field_control"]
decoy.properties["group"] = ["deception"]
gridsim.properties["group"] = ["physical_process"]
collector.properties["group"] = ["telemetry"]
kg.properties["group"] = ["knowledge"]
defender.properties["group"] = ["defense"]
operator.properties["group"] = ["operator"]

# -----------------------------------------------------------------------------
# Zone 0: external / attacker WAN
# -----------------------------------------------------------------------------

wan = net.connect(
    [attacker, edgegw],
    capacity == mbps(50),
    latency == ms(20),
    loss == 0.001,
)
wan.properties["tags"] = ("wan", "attacker_path")

wan[attacker].socket.addrs = ip4("10.10.0.10/24")
wan[edgegw].socket.addrs = ip4("10.10.0.1/24")

# -----------------------------------------------------------------------------
# Zone 1: control-center LAN
# -----------------------------------------------------------------------------

control_lan = net.connect(
    [edgegw, scada, historian]
)

control_lan[edgegw].socket.addrs = ip4("10.20.0.1/24")
control_lan[scada].socket.addrs = ip4("10.20.0.10/24")
control_lan[historian].socket.addrs = ip4("10.20.0.20/24")

# -----------------------------------------------------------------------------
# Zone 2: control-center <-> field/substation backhaul
# -----------------------------------------------------------------------------

backhaul = net.connect(
    [edgegw, fieldgw],
    capacity == mbps(100),
    latency == ms(5),
    loss == 0.0,
)
backhaul.properties["tags"] = ("backhaul", "control_path")

backhaul[edgegw].socket.addrs = ip4("10.25.0.1/30")
backhaul[fieldgw].socket.addrs = ip4("10.25.0.2/30")

# -----------------------------------------------------------------------------
# Zone 3: field / OT control LAN
#
# Both real and decoy controllers are visible behind the field gateway.
# Only the real controller receives a process-side interface.
# -----------------------------------------------------------------------------

ot_lan = net.connect(
    [fieldgw, controller, decoy],
    capacity == mbps(100),
    latency == ms(1),
    loss == 0.0,
)
ot_lan.properties["tags"] = ("ot", "fieldbus")

ot_lan[fieldgw].socket.addrs = ip4("10.30.0.1/24")
ot_lan[controller].socket.addrs = ip4("10.30.0.10/24")
ot_lan[decoy].socket.addrs = ip4("10.30.0.99/24")

# -----------------------------------------------------------------------------
# Zone 4: physical-process LAN
#
# layer == 2 excludes this link from Merge's automatic static routing.
# The real controller is the only cyber-to-physical bridge.
# -----------------------------------------------------------------------------

process_lan = net.connect(
    [controller, gridsim],
    layer == 2,
)

process_lan[controller].socket.addrs = ip4("10.40.0.10/24")
process_lan[gridsim].socket.addrs = ip4("10.40.0.20/24")

# -----------------------------------------------------------------------------
# Zone 5: observation / actuation telemetry plane
#
# edgegw/scada/fieldgw publish observations here.
# collector stores raw/ground-truth records.
#
# IMPORTANT:
# IP forwarding must remain disabled on collector.
# -----------------------------------------------------------------------------

telemetry_lan = net.connect(
    [edgegw, scada, fieldgw, collector],
    layer == 2,
)

telemetry_lan[edgegw].socket.addrs = ip4("10.45.0.1/24")
telemetry_lan[scada].socket.addrs = ip4("10.45.0.10/24")
telemetry_lan[fieldgw].socket.addrs = ip4("10.45.0.20/24")
telemetry_lan[collector].socket.addrs = ip4("10.45.0.30/24")

# -----------------------------------------------------------------------------
# Zone 6: isolated defender / KG / operator plane
#
# collector is the only node shared with telemetry.
# defender does not receive experiment ground truth directly.
# -----------------------------------------------------------------------------

defense_lan = net.connect(
    [collector, kg, defender, operator],
    layer == 2,
)

defense_lan[collector].socket.addrs = ip4("10.50.0.20/24")
defense_lan[kg].socket.addrs = ip4("10.50.0.30/24")
defense_lan[defender].socket.addrs = ip4("10.50.0.40/24")
defense_lan[operator].socket.addrs = ip4("10.50.0.50/24")

# -----------------------------------------------------------------------------
# Execute the experiment model
# -----------------------------------------------------------------------------

experiment(net)