from ecpomdg_final.dbn import CategoricalStageDBN
from ecpomdg_final.types import KnowledgeMode, Observation


def test_posterior_normalizes():
    episodes = [[
        {"true_stage": "RECON", "observation": Observation("NETWORK_RECON")},
        {"true_stage": "ACCESS", "observation": Observation("IEC104_SESSION")},
        {"true_stage": "DER_ENUM", "observation": Observation("GENERAL_INTERROGATION")},
        {"true_stage": "CONTROL", "observation": Observation("CONTROL_SELECT", protocol_phase="SELECT")},
        {"true_stage": "IMPACT", "observation": Observation("CONTROL_EXECUTE", protocol_phase="EXECUTE")},
    ]]
    model = CategoricalStageDBN(KnowledgeMode.TELEMETRY_ONLY).fit(episodes)
    result = model.update(None, Observation("NETWORK_RECON"))
    assert abs(sum(result.posterior.values()) - 1.0) < 1e-12
