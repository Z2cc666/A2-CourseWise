import pathlib,subprocess
from PIL import Image
V={
"A-cols3":"""flowchart LR
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
    K1 ~~~ K3 ~~~ K4 ~~~ K2 ~~~ K5 ~~~ K6 ~~~ K7 ~~~ K8 ~~~ K9
""",
"B-rows3":"""flowchart TB
    subgraph R1[" "]
    direction LR
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
    end
    subgraph R2[" "]
    direction LR
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
    end
    subgraph R3[" "]
    direction LR
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
    end
""",
}
for n,s in V.items():
    pathlib.Path(f'build/t-{n}.mmd').write_text(s)
    subprocess.run(["/tmp/mmd/node_modules/.bin/mmdc","-i",f"build/t-{n}.mmd","-o",f"build/t-{n}.png","-c","build/mmd-config.json","-b","white","-s","2","-p","build/puppeteer-config.json"],capture_output=True)
    im=Image.open(f'build/t-{n}.png'); print(n,im.size,'ratio',round(im.size[1]/im.size[0],2))
    im.convert('RGB').resize((im.size[0]//2,im.size[1]//2)).save(f'build/pv-{n}.png')
