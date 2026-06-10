# -*- coding: utf-8 -*-
"""
Consolida y parametriza las pautas de mantenimiento (cronogramas) de 7 modelos
de camiones Mercedes-Benz en un único dataset apto para modelos de ML.

Fuentes (PDF "01 - Cronograma" de cada modelo):
  1. Arocs 964                      (Euro V-VI, origen Alemán)    v. Julio 2024
  2. New Actros 963.4/964.4         (Euro V-VI, origen Alemán)    v. Febrero 2026
  3. New Actros Brasil 963.4        (Euro V,    origen Brasil)    v. Mayo 2025
  4. Actros WDB 930/932/934         (Euro IV-V, origen Alemán)    v. 1.6 Nov 2019
  5. Arocs 964 Brasil               (Euro V,    origen Brasil)    v. Marzo 2025
  6. Axor WDF 942/944/950/952       (Euro V,    origen Alemán)    v. 1.1 Jun 2017
  7. Axor 9BM/WDB                   (Euro IV-V, origen Brasil)    v. Diciembre 2025

Salidas (carpeta actual):
  - pautas_mantencion_consolidado.csv   -> tabla larga/tidy, una fila por evento de servicio
  - pautas_mantencion_consolidado.json  -> estructura anidada con metadatos + secuencias
  - data_dictionary.md                  -> diccionario de columnas

Las celdas de kilometraje en los PDF estan expresadas "x 1.000 [Km]"; aqui se
almacenan ya multiplicadas a km reales. Las horas se almacenan tal cual.
"""
import csv, json, os
from datetime import datetime, timezone

KM = 1000  # factor "x 1.000 [Km]"

def km(*vals):  return [v * KM for v in vals]
def hr(*vals):  return list(vals)

# Nombre legible por codigo de servicio
NOMBRE = {
    "SI":  "Servicio Inicial",
    "SL*": "Servicio de Lubricacion (solo aceite mineral)",
    "SM1": "Servicio de Mantenimiento 1",
    "SM2": "Servicio de Mantenimiento 2",
    "SM3": "Servicio de Mantenimiento 3",
    "SM4": "Servicio de Mantenimiento 4",
    "SM5": "Servicio de Mantenimiento 5",
    "SM6": "Servicio de Mantenimiento 6",
}

# Parametros comunes a todas las pautas
COMUNES = dict(
    marca="Mercedes-Benz",
    regla="El servicio se realiza por Km, por Horas o por calendario (max 12 meses); lo primero que se cumpla.",
)

# Reglas de tolerancia (varian segun la pauta). intervalo_max_meses=12 en todas.
# A: pautas Alemanas Euro V-VI / Actros y Axor antiguos -> 90 dias + 10% km/horas
# B: pautas Brasil y Axor 9BM/WDB                       -> 12 meses + 1.000 km + 10% horas
TOL_A = dict(tolerancia_dias=90, tolerancia_km="", tolerancia_pct=10, intervalo_max_meses=12)
TOL_B = dict(tolerancia_dias="", tolerancia_km=1000, tolerancia_pct=10, intervalo_max_meses=12)

# ---------------------------------------------------------------------------
# Definicion explicita y verificada de cada cronograma
# ---------------------------------------------------------------------------
MODELOS = []

# === 1. AROCS 964 (Aleman, Euro V-VI) ======================================
_ciclo8 = ["SM2","SM1","SM3","SM1","SM2","SM1","SM4","SM1"]
seq_arocs = ["SI"] + (_ciclo8*4)[:25]   # 26 eventos verificados
MODELOS.append(dict(
    modelo="Arocs 964", familia="Arocs", chasis="964",
    norma_euro="Euro V-VI", origen="Aleman (Europa)", version_pauta="Julio 2024",
    secuencia=seq_arocs, tol=TOL_A,
    ciclo="SI, luego ciclo repetido: SM2, SM1, SM3, SM1, SM2, SM1, SM4, SM1",
    tiempos={"SI":4.6,"SM1":4.4,"SM2":5.1,"SM3":6.0,"SM4":6.0},
    perfiles={
        ("severo","horas"):    hr(*range(600,15601,600)),
        ("severo","km"):       km(*range(20,521,20)),
        ("mixer","horas"):     hr(*range(500,13001,500)),
        ("mixto","horas"):     hr(*range(800,20801,800)),
        ("mixto","km"):        km(*range(40,1041,40)),
        ("forestal","km"):     km(*range(50,1301,50)),
        ("carretero","km"):    km(*range(60,1561,60)),
    },
))

# === 2. NEW ACTROS 963.4 / 964.4 (Aleman, Euro V-VI) =======================
seq_newactros = ["SI"] + (_ciclo8*4)[:25]   # 26 eventos verificados (identico a Arocs)
MODELOS.append(dict(
    modelo="New Actros 963.4 / 964.4", familia="New Actros", chasis="WDB/W1T 963.4 / 964.4",
    norma_euro="Euro V-VI", origen="Aleman (Europa)", version_pauta="Febrero 2026",
    secuencia=seq_newactros, tol=TOL_A,
    ciclo="SI, luego ciclo repetido: SM2, SM1, SM3, SM1, SM2, SM1, SM4, SM1",
    tiempos={"SI":3.4,"SM1":3.3,"SM2":4.0,"SM3":4.8,"SM4":4.8},
    perfiles={
        ("severo","horas"):       hr(*range(600,15601,600)),
        ("severo","km"):          km(*range(20,521,20)),
        ("mixto_mixer","horas"):  hr(*range(500,13001,500)),
        ("mixto","horas"):        hr(*range(800,20801,800)),
        ("mixto","km"):           km(*range(40,1041,40)),
        ("forestal","km"):        km(*range(50,1301,50)),
        ("carretero","km"):       km(*range(60,1561,60)),
    },
))

# === 3. NEW ACTROS BRASIL 963.4 (Brasil, Euro V) ===========================
seq_brasil = ["SM1","SM2","SM1","SM3","SM1","SM2","SM1","SM4"]*2  # 16
MODELOS.append(dict(
    modelo="New Actros Brasil 963.4", familia="New Actros", chasis="9BM963.4 / W1T963.4",
    norma_euro="Euro V", origen="Brasil", version_pauta="Mayo 2025",
    secuencia=seq_brasil, tol=TOL_B,
    ciclo="Ciclo repetido: SM1, SM2, SM1, SM3, SM1, SM2, SM1, SM4 (sin Servicio Inicial)",
    tiempos={"SM1":4.4,"SM2":4.5,"SM3":5.2,"SM4":5.7},
    perfiles={
        ("severo","horas"):  hr(*range(600,9601,600)),
        ("severo","km"):     km(*range(20,321,20)),
        ("mixto","horas"):   hr(*range(800,12801,800)),
        ("mixto","km"):      km(*range(40,641,40)),
        ("forestal","km"):   km(*range(50,801,50)),
        ("carretero","km"):  km(*range(60,961,60)),
    },
))

# === 4. ACTROS WDB 930/932/934 (Aleman, Euro IV-V) =========================
# Secuencia en dos bandas con servicio de lubricacion SL* intercalado.
band1 = ["SI","SL*","SM1","SL*","SM2","SL*","SM1","SL*","SM3","SL*","SM1","SL*",
         "SM2","SL*","SM1","SL*","SM4","SL*","SM1","SL*","SM2","SL*","SM1","SL*","SM5"]   # 25
band2 = ["SL*","SM1","SL*","SM2","SL*","SM1","SL*","SM4","SL*","SM1","SL*","SM2",
         "SL*","SM1","SL*","SM3","SL*","SM1","SL*","SM2","SL*","SM1","SL*","SM6"]          # 24
seq_actros = band1 + band2  # 49

sev_h  = hr(100,200,400,600,800,1000,1200,1400,1600,1800,2000,2200,2400,2600,2800,
            3000,3200,3400,3600,3800,4000,4200,4400,4600,4800) + \
         hr(5000,5200,5400,5600,5800,6000,6200,6400,6600,6800,7000,7200,7400,7600,
            7800,8000,8200,8400,8600,8800,9000,9200,9400,9600)
sev_km = km(5,10,20,30,40,50,60,70,80,90,100,110,120,130,140,150,160,170,180,190,
            200,210,220,230,240) + \
         km(250,260,270,280,290,300,310,320,330,340,350,360,370,380,390,400,410,
            420,430,440,450,460,470,480)
mix_h  = hr(100,360,720,1080,1440,1800,2160,2520,2880,3240,3600,3960,4320,4680,5040,
            5400,5760,6120,6480,6840,7200,7560,7920,8280,8640) + \
         hr(9000,9360,9720,10080,10440,10800,11160,11520,11880,12240,12600,12960,
            13320,13680,14040,14400,14760,15120,15480,15840,16200,16560,16920,17280)
mix_km = km(5,18,36,54,72,90,108,126,144,162,180,198,216,234,252,270,288,306,324,342,
            360,378,396,414,432) + \
         km(450,468,486,504,522,540,558,576,594,612,630,648,666,684,702,720,738,756,
            774,792,810,828,846,864)
car_km = km(5,25,50,75,100,125,150,175,200,225,250,275,300,325,350,375,400,425,450,
            475,500,525,550,575,600) + \
         km(625,650,675,700,725,750,775,800,825,850,875,900,925,950,975,1000,1025,
            1050,1075,1100,1125,1150,1175,1200)
MODELOS.append(dict(
    modelo="Actros WDB 930/932/934", familia="Actros", chasis="WDB 930, 932, 934",
    norma_euro="Euro IV-V", origen="Aleman (Europa)", version_pauta="1.6 (Nov 2019)",
    secuencia=seq_actros, tol=TOL_A,
    ciclo="SI, luego ciclo repetido: SM1, SM2, SM1, SM3, SM1, SM2, SM1, SM4 (con SL* intercalado solo en motores con aceite mineral)",
    tiempos={"SI":1.2,"SL*":2.7,"SM1":4.2,"SM2":6.4,"SM3":10.8,"SM4":12.6,"SM5":13.2,"SM6":15.0},
    perfiles={
        ("severo","horas"):   sev_h,
        ("severo","km"):      sev_km,
        ("mixto","horas"):    mix_h,
        ("mixto","km"):       mix_km,
        ("carretero","km"):   car_km,
    },
    notas=[
        "SL* (Servicio de Lubricacion) aplica SOLO a motores que usan aceite mineral (hoja 228.3).",
        "Equipado con sistema Telligent: el intervalo real puede acortarse segun la carga.",
        "Servicios anuales complementarios: cada 2 anios SA1+SA2, cada 3 anios SA1+SA3, cada 6 anios SA1+SA2+SA3.",
    ],
))

# === 5. AROCS 964 BRASIL (Brasil, Euro V) ==================================
# Misma estructura que New Actros Aleman (con perfil mixto_mixer por horas).
seq_arocs_br = ["SI"] + (_ciclo8*4)[:25]   # 26 eventos, identico patron a Arocs
MODELOS.append(dict(
    modelo="Arocs 964 Brasil", familia="Arocs", chasis="964 (Brasil)",
    norma_euro="Euro V", origen="Brasil", version_pauta="Marzo 2025",
    secuencia=seq_arocs_br, tol=TOL_B,
    ciclo="SI, luego ciclo repetido: SM2, SM1, SM3, SM1, SM2, SM1, SM4, SM1",
    tiempos={"SI":6.9,"SM1":6.9,"SM2":7.2,"SM3":7.8,"SM4":9.1},
    perfiles={
        ("severo","horas"):       hr(*range(600,15601,600)),
        ("severo","km"):          km(*range(20,521,20)),
        ("mixto_mixer","horas"):  hr(*range(500,13001,500)),
        ("mixto","horas"):        hr(*range(800,20801,800)),
        ("mixto","km"):           km(*range(40,1041,40)),
        ("forestal","km"):        km(*range(50,1301,50)),
        ("carretero","km"):       km(*range(60,1561,60)),
    },
))

# === 6. AXOR WDF 942/944/950/952 (Aleman, Euro V) ==========================
# Banda unica de 25 eventos con SL* intercalado (mismos intervalos que Actros
# antiguo banda 1). Termina en SM3 (Axor solo llega a SM4).
seq_axor_wdf = ["SI","SL*","SM1","SL*","SM2","SL*","SM1","SL*","SM3","SL*","SM1","SL*",
                "SM2","SL*","SM1","SL*","SM4","SL*","SM1","SL*","SM2","SL*","SM1","SL*","SM3"]  # 25
axor_sev_h  = hr(100,200,400,600,800,1000,1200,1400,1600,1800,2000,2200,2400,2600,2800,
                 3000,3200,3400,3600,3800,4000,4200,4400,4600,4800)
axor_sev_km = km(5,10,20,30,40,50,60,70,80,90,100,110,120,130,140,150,160,170,180,190,
                 200,210,220,230,240)
axor_mix_h  = hr(100,360,720,1080,1440,1800,2160,2520,2880,3240,3600,3960,4320,4680,5040,
                 5400,5760,6120,6480,6840,7200,7560,7920,8280,8640)
axor_mix_km = km(5,18,36,54,72,90,108,126,144,162,180,198,216,234,252,270,288,306,324,342,
                 360,378,396,414,432)
axor_car_km = km(5,25,50,75,100,125,150,175,200,225,250,275,300,325,350,375,400,425,450,
                 475,500,525,550,575,600)
MODELOS.append(dict(
    modelo="Axor WDF 942/944/950/952", familia="Axor", chasis="WDF 942/944/950/952",
    norma_euro="Euro V", origen="Aleman (Europa)", version_pauta="1.1 (Jun 2017)",
    secuencia=seq_axor_wdf, tol=TOL_A,
    ciclo="SI, luego ciclo repetido: SM1, SM2, SM1, SM3, SM1, SM2, SM1, SM4 (con SL* intercalado solo en motores con aceite mineral)",
    tiempos={"SI":1.4,"SL*":2.3,"SM1":4.0,"SM2":6.0,"SM3":8.2,"SM4":10.0},
    perfiles={
        ("severo","horas"):   axor_sev_h,
        ("severo","km"):      axor_sev_km,
        ("mixto","horas"):    axor_mix_h,
        ("mixto","km"):       axor_mix_km,
        ("carretero","km"):   axor_car_km,
    },
    notas=[
        "SL* (Servicio de Lubricacion) aplica SOLO a motores que usan aceite mineral.",
        "Servicios anuales (no modelados por km/horas): SA1 cada 1 anio (4.0 h), "
        "SA2 cada 2 anios (segun modelo/condicion), SA3 cada 3 anios (2.7 h). "
        "Complementarios: 2 anios SA1+SA2, 3 anios SA1+SA3, 6 anios SA1+SA2+SA3.",
        "Cambio de aceite de transmisiones/ejes con lubricante mineral en SM2, SM3 y SM4; "
        "con lubricante sintetico en SM3 y SM4.",
        "Vehiculos con toma de fuerza al motor o caja: aplicar solo intervalo severo o mixto.",
    ],
))

# === 7. AXOR 9BM/WDB (Brasil, Euro IV-V) ===================================
# Ciclo estandar de 24 eventos, sin SI ni SL*.
seq_axor_9bm = ["SM1","SM2","SM1","SM3","SM1","SM2","SM1","SM4"]*3   # 24
MODELOS.append(dict(
    modelo="Axor 9BM/WDB",
    familia="Axor",
    chasis="WDB 940/942/944/950.5/950.6/952.5/952.6/954.5, 9BM 958.2/958.4",
    norma_euro="Euro IV-V", origen="Brasil", version_pauta="Diciembre 2025",
    secuencia=seq_axor_9bm, tol=TOL_B,
    ciclo="Ciclo repetido: SM1, SM2, SM1, SM3, SM1, SM2, SM1, SM4 (sin Servicio Inicial)",
    tiempos={"SM1":3.7,"SM2":5.3,"SM3":7.1,"SM4":7.6},
    perfiles={
        ("severo","horas"):   hr(*range(200,4801,200)),
        ("severo","km"):      km(*range(10,241,10)),
        ("mixto","horas"):    hr(*range(400,9601,400)),
        ("mixto","km"):       km(*range(20,481,20)),
        ("carretero","km"):   km(*range(40,961,40)),
    },
    notas=[
        "Algunos vehiculos equipan sistema Telligent: el intervalo real puede acortarse segun la carga.",
        "Cambio de aceite de transmisiones/ejes con lubricante mineral en SM2, SM3 y SM4; "
        "con lubricante sintetico en SM3 y SM4.",
        "Vehiculos con toma de fuerza al motor o caja: aplicar solo intervalo severo o mixto.",
    ],
))

# ---------------------------------------------------------------------------
# Construccion de la tabla larga (tidy) + estructura JSON
# ---------------------------------------------------------------------------
UNIDAD = {"km": "km", "horas": "h"}
rows = []
for m in MODELOS:
    seq = m["secuencia"]
    for (perfil, metrica), valores in m["perfiles"].items():
        if len(valores) != len(seq):
            raise ValueError(f"{m['modelo']} {perfil}/{metrica}: "
                             f"{len(valores)} valores vs {len(seq)} eventos de secuencia")
        prev = 0
        for i, (cod, val) in enumerate(zip(seq, valores), start=1):
            rows.append({
                "marca": COMUNES["marca"],
                "familia": m["familia"],
                "modelo": m["modelo"],
                "chasis": m["chasis"],
                "norma_euro": m["norma_euro"],
                "origen": m["origen"],
                "version_pauta": m["version_pauta"],
                "perfil_operacion": perfil,
                "metrica": metrica,
                "unidad": UNIDAD[metrica],
                "evento_secuencia": i,
                "servicio_codigo": cod,
                "servicio_nombre": NOMBRE[cod],
                "valor_acumulado": val,
                "intervalo_incremental": val - prev,
                "tiempo_trabajo_h": m["tiempos"].get(cod, ""),
                "ciclo_mantenimiento": m["ciclo"],
                "tolerancia_dias": m["tol"]["tolerancia_dias"],
                "tolerancia_km": m["tol"]["tolerancia_km"],
                "tolerancia_pct": m["tol"]["tolerancia_pct"],
                "intervalo_max_meses": m["tol"]["intervalo_max_meses"],
                "requiere_aceite_mineral": (cod == "SL*"),
            })
            prev = val

# Orden estable
rows.sort(key=lambda r: (r["modelo"], r["perfil_operacion"], r["metrica"], r["evento_secuencia"]))

COLS = ["marca","familia","modelo","chasis","norma_euro","origen","version_pauta",
        "perfil_operacion","metrica","unidad","evento_secuencia","servicio_codigo",
        "servicio_nombre","valor_acumulado","intervalo_incremental","tiempo_trabajo_h",
        "ciclo_mantenimiento","tolerancia_dias","tolerancia_km","tolerancia_pct",
        "intervalo_max_meses","requiere_aceite_mineral"]

base = os.path.dirname(os.path.abspath(__file__))
csv_path = os.path.join(base, "pautas_mantencion_consolidado.csv")
with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
    w = csv.DictWriter(f, fieldnames=COLS)
    w.writeheader()
    w.writerows(rows)

# JSON anidado con metadatos + secuencias + reglas
doc = {
    "generado": datetime.now(timezone.utc).isoformat(),
    "descripcion": "Pautas de mantenimiento consolidadas y parametrizadas (Mercedes-Benz, Grupo Kaufmann).",
    "parametros_comunes": COMUNES,
    "perfiles_operacion": {
        "severo": "Uso severo (alto polvo, altura >2500 msnm, condiciones exigentes).",
        "mixto": "Uso mixto carretera/ciudad.",
        "carretero": "Uso 100% carretera (intervalo mas largo).",
        "forestal": "Traslado de material desde faenas forestales a aserraderos.",
        "mixer": "Camion mixer urbano (bajo polvo, baja altura).",
        "mixto_mixer": "Mixto medido por horas para mixer (New Actros / Arocs Brasil).",
    },
    "modelos": [
        {
            "modelo": m["modelo"], "familia": m["familia"], "chasis": m["chasis"],
            "norma_euro": m["norma_euro"], "origen": m["origen"],
            "version_pauta": m["version_pauta"], "ciclo_mantenimiento": m["ciclo"],
            "tolerancia": m["tol"],
            "n_eventos": len(m["secuencia"]),
            "secuencia_servicios": m["secuencia"],
            "tiempos_trabajo_h": m["tiempos"],
            "perfiles_disponibles": [f"{p}/{me}" for (p, me) in m["perfiles"].keys()],
            "notas": m.get("notas", []),
        } for m in MODELOS
    ],
}
json_path = os.path.join(base, "pautas_mantencion_consolidado.json")
with open(json_path, "w", encoding="utf-8") as f:
    json.dump(doc, f, ensure_ascii=False, indent=2)

print(f"Filas CSV: {len(rows)}")
print(f"Modelos:   {len(MODELOS)}")
for m in MODELOS:
    print(f"  - {m['modelo']:32} eventos={len(m['secuencia']):3}  perfiles={len(m['perfiles'])}")
print("CSV  ->", csv_path)
print("JSON ->", json_path)
