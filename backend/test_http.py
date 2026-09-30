"""Teste HTTP síncrono contra o uvicorn em :8100 (valida o servidor real).

Precisa de uma imagem de teste em SEED_IMAGES_DIR/cad_01.jpg (.env ou variável
de ambiente — ver config.py). Este repo não vem com fotos de exemplo: rode
`python generate_placeholders.py` primeiro, ou aponte SEED_IMAGES_DIR para uma
pasta com suas próprias fotos.
"""

import sys
import time

import httpx

import config

BASE = "http://127.0.0.1:8100"
SEED_IMAGES = config.SEED_IMAGES_DIR


def main():
    # espera o /health subir
    for _ in range(30):
        try:
            if httpx.get(f"{BASE}/api/health", timeout=5).status_code == 200:
                break
        except Exception:
            time.sleep(1)
    else:
        sys.exit("backend não respondeu")

    with httpx.Client(base_url=BASE, timeout=60) as c:
        print("[health]", c.get("/api/health").json())
        print("[lookup]", c.post("/api/lookup", json={"numero_pedido": "ped-90001"}).json())
        print("[checklist] itens:", len(c.get("/api/checklist/cadeira").json()["itens"]))

        caminho_img = SEED_IMAGES / "cad_01.jpg"
        if not caminho_img.exists():
            sys.exit(
                f"Imagem ausente: {caminho_img}.\n"
                f"Rode 'python generate_placeholders.py' ou aponte SEED_IMAGES_DIR "
                f"para uma pasta com suas próprias fotos."
            )
        img = caminho_img.read_bytes()
        r = c.post(
            "/api/analisar",
            files={"imagem": ("cad_01.jpg", img, "image/jpeg")},
            data={
                "numero_pedido": "PED-90001",
                "sku": "CAD-OFF-PRO",
                "descricao": "Perna traseira trincada, caixa amassada na entrega.",
                "checklist": "perna_quebrada",
            },
        )
        print("\n[analisar]", r.status_code)
        if r.status_code == 200:
            j = r.json()
            v = j["veredito"]
            print("  veredito:", v["classificacao"], "| confianca:", v["confianca"])
            print("  racional:", v["racional"])
            print("  sinais:", v.get("sinais_observados"))
            print("  precedentes:", len(j["precedentes"]), "| funnel:", j["funnel"])
            print("  imagem_url:", j["imagem_url"])
            print("  _meta:", v.get("_meta"))
            # valida que a imagem é servida
            iu = c.get(j["imagem_url"])
            print("  GET imagem_url:", iu.status_code, iu.headers.get("content-type"))
        else:
            print("  ERRO:", r.json())

        a = c.get("/api/analytics").json()
        print("\n[analytics] por_classificacao:", a["por_classificacao"])

        # confirma que o novo chamado entrou como em_analise
        pend = c.get("/api/chamados/pendentes").json()
        print("\n[pendentes]:", len(pend), "chamado(s) em_analise")


if __name__ == "__main__":
    main()
