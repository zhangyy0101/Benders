"""Unambiguous, duplicate-free Route-A experiment configurations."""
def experiment_configurations(full=False):
    configs=[
      {"algorithm":"plain_core_mip_without_valid_inequalities","plain":True,"valid":False,"symmetry":False},
      {"algorithm":"strengthened_core_mip","alns":False,"proof":False,"refine":False},
      {"algorithm":"strengthened_core_mip_alns","proof":False,"refine":False},
      {"algorithm":"strengthened_core_mip_alns_proof","refine":False},
      {"algorithm":"full_with_attribute_refinement","refine":True},
      {"algorithm":"without_alns_with_proof_and_refinement","alns":False,"proof":True,"refine":True},
    ]
    if full:
      configs += [{"algorithm":"alloc_continuous","domain":"continuous"}]
      configs += [{"algorithm":f"handling_{x}","rate":x} for x in (.25,.5,1.5)]
      configs += [{"algorithm":f"epsilon_{x}","epsilon":x} for x in (0,.005,.02,.05)]
      configs += [{"algorithm":f"attribute_{x}","attributes":x} for x in ("pod","weight","height")]
      configs += [{"algorithm":f"release_{x}","release":x} for x in ("legacy_sorted","conservative")]
      configs += [{"algorithm":"with_symmetry_breaking","symmetry":True}]
    names=[c["algorithm"] for c in configs]
    if len(names)!=len(set(names)):raise AssertionError("duplicate experiment configuration")
    return configs
def core_budget(total,config):
    total=float(total)
    if config.get("plain") or (not config.get("alns",True) and not config.get("proof",True)):return {"phase1":total,"alns":0.0,"phase3":0.0}
    if not config.get("proof",True):return {"phase1":.25*total,"alns":.75*total,"phase3":0.0}
    if not config.get("alns",True):return {"phase1":.5*total,"alns":0.0,"phase3":.5*total}
    return {"phase1":.25*total,"alns":.40*total,"phase3":.35*total}
