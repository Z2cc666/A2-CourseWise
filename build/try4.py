import re,pathlib,subprocess,json
VARIANTS={
"LR-nolinks":"""flowchart LR
    subgraph K1["assignment-1-brief"]
        direction TB
        K1a["v1 · 14 Sep<br/>SUPERSEDED"] --> K1b["v2 · 28 Sep<br/>CURRENT"]
    end
    subgraph K3["exam-format"]
        direction TB
        K3a["v1 · 10 Sep<br/>SUPERSEDED"] --> K3b["v2 · 1 Oct<br/>CURRENT"]
    end
    subgraph K4["plagiarism-policy"]
        direction TB
        K4a["v1 · 1 Sep<br/>ARCHIVED"] --> K4b["v2 · 15 Oct<br/>CURRENT"]
    end
    subgraph K2["assignment-2-brief"]
        direction TB
        K2a["v1 · 20 Oct<br/>CURRENT"]
    end
    subgraph K5["module-faq"]
        direction TB
        K5a["v1 · 20 Oct<br/>CURRENT"]
    end
    subgraph K6["module-timeline"]
        direction TB
        K6a["v1 · 12 Oct<br/>CURRENT"]
    end
    subgraph K7["office-hours"]
        direction TB
        K7a["v1 · 18 Oct<br/>CURRENT"]
    end
    subgraph K8["reading-list"]
        direction TB
        K8a["v1 · 5 Oct<br/>CURRENT"]
    end
    subgraph K9["room-booking"]
        direction TB
        K9a["v1 · 25 Sep<br/>CURRENT"]
    end
""",
"TB-grid3":"""flowchart TB
    subgraph R1[" "]
      direction LR
      K1["assignment-1-brief<br/>v1 14 Sep SUPERSEDED<br/>v2 28 Sep CURRENT"]
      K2["assignment-2-brief<br/>v1 20 Oct CURRENT"]
      K3["exam-format<br/>v1 10 Sep SUPERSEDED<br/>v2 1 Oct CURRENT"]
    end
    subgraph R2[" "]
      direction LR
      K4["plagiarism-policy<br/>v1 1 Sep ARCHIVED<br/>v2 15 Oct CURRENT"]
      K5["module-faq<br/>v1 20 Oct CURRENT"]
      K6["module-timeline<br/>v1 12 Oct CURRENT"]
    end
    subgraph R3[" "]
      direction LR
      K7["office-hours<br/>v1 18 Oct CURRENT"]
      K8["reading-list<br/>v1 5 Oct CURRENT"]
      K9["room-booking<br/>v1 25 Sep CURRENT"]
    end
""",
}
for name,src in VARIANTS.items():
    pathlib.Path(f'build/t-{name}.mmd').write_text(src)
    subprocess.run(["/tmp/mmd/node_modules/.bin/mmdc","-i",f"build/t-{name}.mmd","-o",f"build/t-{name}.png","-c","build/mmd-config.json","-b","white","-s","2","-p","build/puppeteer-config.json"],capture_output=True)
    from PIL import Image
    im=Image.open(f'build/t-{name}.png'); print(name,im.size,'ratio',round(im.size[1]/im.size[0],2))
