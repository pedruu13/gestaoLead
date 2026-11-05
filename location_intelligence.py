import re
import unicodedata


def _normalize(value):
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(character for character in text if not unicodedata.combining(character))
    return re.sub(r"[^a-z0-9]+", " ", text.casefold()).strip()


BRAZIL_STATES = {
    "AC": ("Acre", ("Rio Branco - AC", "Cruzeiro do Sul - AC", "Sena Madureira - AC")),
    "AL": ("Alagoas", ("Maceió - AL", "Arapiraca - AL", "Rio Largo - AL", "Palmeira dos Índios - AL")),
    "AP": ("Amapá", ("Macapá - AP", "Santana - AP", "Laranjal do Jari - AP")),
    "AM": ("Amazonas", ("Manaus - AM", "Parintins - AM", "Itacoatiara - AM", "Manacapuru - AM")),
    "BA": ("Bahia", ("Salvador - BA", "Feira de Santana - BA", "Vitória da Conquista - BA", "Lauro de Freitas - BA", "Camaçari - BA", "Itabuna - BA")),
    "CE": ("Ceará", ("Fortaleza - CE", "Juazeiro do Norte - CE", "Sobral - CE", "Maracanaú - CE", "Crato - CE")),
    "DF": ("Distrito Federal", ("Brasília - DF", "Águas Claras - DF", "Taguatinga - DF", "Lago Sul - Brasília", "Guará - DF")),
    "ES": ("Espírito Santo", ("Vitória - ES", "Vila Velha - ES", "Serra - ES", "Cariacica - ES", "Linhares - ES")),
    "GO": ("Goiás", ("Goiânia - GO", "Aparecida de Goiânia - GO", "Anápolis - GO", "Rio Verde - GO", "Catalão - GO")),
    "MA": ("Maranhão", ("São Luís - MA", "Imperatriz - MA", "São José de Ribamar - MA", "Caxias - MA")),
    "MT": ("Mato Grosso", ("Cuiabá - MT", "Várzea Grande - MT", "Rondonópolis - MT", "Sinop - MT", "Sorriso - MT")),
    "MS": ("Mato Grosso do Sul", ("Campo Grande - MS", "Dourados - MS", "Três Lagoas - MS", "Corumbá - MS")),
    "MG": ("Minas Gerais", ("Belo Horizonte - MG", "Uberlândia - MG", "Contagem - MG", "Juiz de Fora - MG", "Uberaba - MG", "Montes Claros - MG")),
    "PA": ("Pará", ("Belém - PA", "Ananindeua - PA", "Santarém - PA", "Marabá - PA", "Parauapebas - PA")),
    "PB": ("Paraíba", ("João Pessoa - PB", "Campina Grande - PB", "Santa Rita - PB", "Patos - PB")),
    "PR": ("Paraná", ("Curitiba - PR", "Londrina - PR", "Maringá - PR", "Cascavel - PR", "São José dos Pinhais - PR", "Ponta Grossa - PR")),
    "PE": ("Pernambuco", ("Recife - PE", "Jaboatão dos Guararapes - PE", "Olinda - PE", "Caruaru - PE", "Petrolina - PE")),
    "PI": ("Piauí", ("Teresina - PI", "Parnaíba - PI", "Picos - PI", "Floriano - PI")),
    "RJ": ("Rio de Janeiro", ("Rio de Janeiro - RJ", "Niterói - RJ", "Duque de Caxias - RJ", "Nova Iguaçu - RJ", "São Gonçalo - RJ", "Petrópolis - RJ")),
    "RN": ("Rio Grande do Norte", ("Natal - RN", "Mossoró - RN", "Parnamirim - RN", "Caicó - RN")),
    "RS": ("Rio Grande do Sul", ("Porto Alegre - RS", "Caxias do Sul - RS", "Canoas - RS", "Pelotas - RS", "Santa Maria - RS", "Novo Hamburgo - RS")),
    "RO": ("Rondônia", ("Porto Velho - RO", "Ji-Paraná - RO", "Ariquemes - RO", "Vilhena - RO")),
    "RR": ("Roraima", ("Boa Vista - RR", "Rorainópolis - RR", "Caracaraí - RR")),
    "SC": ("Santa Catarina", ("Florianópolis - SC", "Joinville - SC", "Blumenau - SC", "São José - SC", "Itajaí - SC", "Balneário Camboriú - SC")),
    "SP": ("São Paulo", ("São Paulo - SP", "Campinas - SP", "Guarulhos - SP", "São José dos Campos - SP", "Ribeirão Preto - SP", "Sorocaba - SP")),
    "SE": ("Sergipe", ("Aracaju - SE", "Nossa Senhora do Socorro - SE", "Lagarto - SE", "Itabaiana - SE")),
    "TO": ("Tocantins", ("Palmas - TO", "Araguaína - TO", "Gurupi - TO", "Porto Nacional - TO")),
}


US_STATES = {
    "FL": ("Florida", ("Miami - FL", "Tampa - FL", "Orlando - FL", "Jacksonville - FL", "Boca Raton - FL", "Fort Lauderdale - FL")),
    "TX": ("Texas", ("Houston - TX", "Dallas - TX", "Austin - TX", "San Antonio - TX", "Fort Worth - TX")),
    "CA": ("California", ("Los Angeles - CA", "San Diego - CA", "San Jose - CA", "Sacramento - CA", "Beverly Hills - CA")),
    "NY": ("New York", ("New York City - NY", "Buffalo - NY", "Rochester - NY", "Albany - NY")),
    "AZ": ("Arizona", ("Phoenix - AZ", "Scottsdale - AZ", "Tucson - AZ", "Mesa - AZ")),
    "NC": ("North Carolina", ("Charlotte - NC", "Raleigh - NC", "Greensboro - NC", "Durham - NC")),
    "GA": ("Georgia", ("Atlanta - GA", "Savannah - GA", "Augusta - GA", "Alpharetta - GA")),
    "TN": ("Tennessee", ("Nashville - TN", "Memphis - TN", "Knoxville - TN", "Chattanooga - TN")),
    "CO": ("Colorado", ("Denver - CO", "Colorado Springs - CO", "Aurora - CO", "Boulder - CO")),
}


EUROPE_COUNTRIES = {
    "PT": ("Portugal", ("Lisbon - Portugal", "Porto - Portugal", "Braga - Portugal", "Coimbra - Portugal", "Cascais - Portugal")),
    "ES": ("Spain", ("Madrid - Spain", "Barcelona - Spain", "Valencia - Spain", "Málaga - Spain", "Seville - Spain")),
    "IT": ("Italy", ("Milan - Italy", "Rome - Italy", "Turin - Italy", "Bologna - Italy", "Florence - Italy")),
    "UK": ("United Kingdom", ("London - UK", "Manchester - UK", "Birmingham - UK", "Leeds - UK", "Bristol - UK")),
    "IE": ("Ireland", ("Dublin - Ireland", "Cork - Ireland", "Galway - Ireland", "Limerick - Ireland")),
    "NL": ("Netherlands", ("Amsterdam - Netherlands", "Rotterdam - Netherlands", "Utrecht - Netherlands", "The Hague - Netherlands")),
}


def _catalog(region):
    if region == "br":
        return BRAZIL_STATES, ("estado de ",), (" estado",)
    if region == "us":
        return US_STATES, ("state of ",), (" state",)
    return EUROPE_COUNTRIES, ("pais ", "country "), (" pais", " country")


def _group_for_value(region, value):
    catalog, prefixes, suffixes = _catalog(region)
    normalized = _normalize(value)
    explicit_group = False
    for prefix in prefixes:
        if normalized.startswith(prefix):
            normalized = normalized[len(prefix):].strip()
            explicit_group = True
    for suffix in suffixes:
        if normalized.endswith(suffix):
            normalized = normalized[:-len(suffix)].strip()
            explicit_group = True
    raw_upper = str(value or "").strip().upper()
    for code, (name, locations) in catalog.items():
        if raw_upper == code or normalized == _normalize(name):
            return {"code": code, "name": name, "locations": locations}
    return None


def expand_locations(region, values, per_group=5, max_total=24):
    if isinstance(values, str):
        values = re.split(r"[\n,;]+", values)
    locations = []
    expansions = []
    seen = set()
    for raw_value in values or []:
        value = re.sub(r"\s+", " ", str(raw_value or "")).strip()
        if not value:
            continue
        group = _group_for_value(region, value)
        candidates = list(group["locations"][:per_group]) if group else [value]
        if group:
            expansions.append({"entrada": value, "grupo": group["name"], "codigo": group["code"], "locais": candidates})
        for candidate in candidates:
            key = _normalize(candidate)
            if key and key not in seen:
                locations.append(candidate)
                seen.add(key)
            if len(locations) >= max_total:
                break
        if len(locations) >= max_total:
            break
    return {"locations": locations, "expansions": expansions}
