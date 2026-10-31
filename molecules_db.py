"""Single source of truth for the molecules the app can build."""

MOLECULE_DB = {
    # Alkanes / alkenes / alkynes / aromatics
    "methane": "C", "ethane": "CC", "propane": "CCC", "butane": "CCCC",
    "pentane": "CCCCC", "hexane": "CCCCCC", "ethene": "C=C", "ethyne": "C#C",
    "benzene": "c1ccccc1",
    # Alcohols
    "methanol": "CO", "ethanol": "CCO", "propanol": "CCCO", "butanol": "CCCCO",
    "isopropanol": "CC(O)C", "glycerol": "C(C(CO)O)O",
    # Acids
    "formic acid": "C(=O)O", "acetic acid": "CC(=O)O", "propanoic acid": "CCC(=O)O",
    "butanoic acid": "CCCC(=O)O", "benzoic acid": "c1ccc(cc1)C(=O)O",
    # Amines
    "methylamine": "CN", "ethylamine": "CCN", "aniline": "c1ccccc1N",
    # Aldehydes and ketones
    "formaldehyde": "C=O", "acetaldehyde": "CC=O", "acetone": "CC(=O)C",
    # Carbohydrates
    "glucose": "OC[C@H]1O[C@@H](O)[C@H](O)[C@@H](O)[C@H]1O",
    "fructose": "OCC1(O)OCC(O)C(O)C1O",
    "sucrose": "OC[C@H]1O[C@@](CO)(O[C@H]2O[C@H](CO)[C@@H](O)[C@H](O)[C@H]2O)[C@@H](O)[C@@H]1O",
    # Amino acids
    "glycine": "NCC(=O)O", "alanine": "CC(C(=O)O)N", "valine": "CC(C)C(C(=O)O)N",
    "leucine": "CC(C)CC(C(=O)O)N", "phenylalanine": "C1=CC=C(C=C1)CC(C(=O)O)N",
    "tryptophan": "C1=CC=C2C(=C1)C(=CN2)CC(C(=O)O)N",
    # Inorganic
    "water": "O", "ammonia": "N", "carbon dioxide": "O=C=O", "nitric acid": "O=[N+]([O-])O",
    "sulfuric acid": "OS(=O)(=O)O", "phosphoric acid": "OP(=O)(O)O",
    "hydrogen peroxide": "OO", "ozone": "[O-][O+]=O",
    # Nucleobases
    "adenine": "Nc1ncnc2[nH]cnc12", "guanine": "Nc1nc2[nH]cnc2c(=O)[nH]1",
    "cytosine": "Nc1cc[nH]c(=O)n1", "uracil": "C1=CC(=O)NC(=O)N1",
    "thymine": "Cc1c[nH]c(=O)[nH]c1=O",
    # Other biological / drugs
    "cholesterol": "C[C@H](CCCC(C)C)[C@H]1CC[C@@H]2[C@@]1(CC[C@H]3[C@H]2CC=C4[C@@]3(CC[C@@H](C4)O)C)C",
    "caffeine": "CN1C=NC2=C1C(=O)N(C(=O)N2C)C", "nicotine": "CN1CCCC1C2=CN=CC=C2",
    # Gases
    "oxygen": "O=O", "hydrogen": "[H][H]", "nitrogen": "N#N", "chlorine": "ClCl",
    "fluorine": "FF",
    # Common drugs
    "aspirin": "CC(=O)Oc1ccccc1C(=O)O", "paracetamol": "CC(=O)NC1=CC=C(C=C1)O",
    "acetylsalicylic acid": "CC(=O)Oc1ccccc1C(=O)O",
}
