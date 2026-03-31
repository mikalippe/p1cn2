from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from azure.data.tables import TableServiceClient
from azure.storage.blob import BlobServiceClient, generate_blob_sas, BlobSasPermissions
from datetime import datetime, timedelta, timezone
import uuid
import os

app = Flask(__name__)
app.secret_key = "ecommerce-secret-key-2026"

# ─── CREDENCIAIS AZURE ────────────────────────────────────────────────────────
ACCOUNT_NAME       = os.environ.get("AZURE_ACCOUNT_NAME")
ACCOUNT_KEY        = os.environ.get("AZURE_ACCOUNT_KEY")
CONNECTION_STRING  = os.environ.get("AZURE_CONNECTION_STRING")
CONTAINER_NAME = "felipe-imagens"

# ─── CLIENTES AZURE ───────────────────────────────────────────────────────────
blob_service   = BlobServiceClient.from_connection_string(CONNECTION_STRING)
table_service  = TableServiceClient.from_connection_string(CONNECTION_STRING)

# ─── INICIALIZAÇÃO ────────────────────────────────────────────────────────────
def garantir_container():
    """Garante que o container existe, criando se necessário."""
    container_client = blob_service.get_container_client(CONTAINER_NAME)
    try:
        container_client.get_container_properties()
    except Exception:
        try:
            blob_service.create_container(CONTAINER_NAME, public_access="blob")
            print(f"[Azure] Container criado com sucesso.")
        except Exception as e:
            print(f"[Azure] Erro ao criar container: {e}")


def init_azure():
    garantir_container()
    for table in ["FelipeProd", "FelipeClie", "FelipePedi"]:
        try:
            table_service.create_table(table)
            print(f"[Azure] Tabela '{table}' criada.")
        except Exception:
            pass

init_azure()

# ═══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def upload_imagem(file):
    """Faz upload de imagem para o Blob Storage e retorna URL com SAS token."""
    from azure.storage.blob import ContentSettings
    garantir_container()

    nome_seguro = file.filename.replace(" ", "_")
    blob_name = f"{uuid.uuid4()}_{nome_seguro}"
    blob_client = blob_service.get_blob_client(container=CONTAINER_NAME, blob=blob_name)

    conteudo = file.read()
    content_type = file.content_type or "image/jpeg"
    blob_client.upload_blob(
        conteudo,
        overwrite=True,
        content_settings=ContentSettings(content_type=content_type)
    )

    sas = generate_blob_sas(
        account_name=ACCOUNT_NAME,
        container_name=CONTAINER_NAME,
        blob_name=blob_name,
        account_key=ACCOUNT_KEY,
        permission=BlobSasPermissions(read=True),
        expiry=datetime.now(timezone.utc) + timedelta(days=365),
    )
    url = f"https://{ACCOUNT_NAME}.blob.core.windows.net/{CONTAINER_NAME}/{blob_name}?{sas}"
    print(f"[Azure] Imagem enviada: {blob_name}")
    return url


def normalizar_felipeprod(e):
    """Converte TableEntity de felipeprod para dict simples com valores padrão."""
    return {
        "PartitionKey": e.get("PartitionKey", "FelipeProd"),
        "RowKey":       e.get("RowKey", ""),
        "Marca":        e.get("Marca", ""),
        "Modelo":       e.get("Modelo", ""),
        "Valor":        float(e.get("Valor", 0) or 0),
        "Quantidade":   int(e.get("Quantidade", 0) or 0),
        "FotoURL":      e.get("FotoURL", ""),
        "CriadoEm":     e.get("CriadoEm", ""),
    }

def normalizar_felipeclie(e):
    return {
        "PartitionKey": e.get("PartitionKey", "FelipeClie"),
        "RowKey":       e.get("RowKey", ""),
        "Nome":         e.get("Nome", ""),
        "Email":        e.get("Email", ""),
        "Telefone":     e.get("Telefone", ""),
        "Endereco":     e.get("Endereco", ""),
        "CriadoEm":     e.get("CriadoEm", ""),
    }

def normalizar_felipepedi(e):
    return {
        "PartitionKey": e.get("PartitionKey", "FelipePedi"),
        "RowKey":       e.get("RowKey", ""),
        "ClienteId":    e.get("ClienteId", ""),
        "ProdutoId":    e.get("ProdutoId", ""),
        "ProdutoNome":  e.get("ProdutoNome", ""),
        "Quantidade":   int(e.get("Quantidade", 0) or 0),
        "Total":        float(e.get("Total", 0) or 0),
        "Pagamento":    e.get("Pagamento", ""),
        "Entrega":      e.get("Entrega", ""),
        "Status":       e.get("Status", ""),
        "CriadoEm":     e.get("CriadoEm", ""),
    }

def listar_entidades(table_name, filtro=None):
    client = table_service.get_table_client(table_name)
    entidades = list(client.query_entities(filtro)) if filtro else list(client.list_entities())
    if table_name == "FelipeProd":
        return [normalizar_felipeprod(e) for e in entidades]
    if table_name == "FelipeClie":
        return [normalizar_felipeclie(e) for e in entidades]
    if table_name == "FelipePedi":
        return [normalizar_felipepedi(e) for e in entidades]
    return entidades

def obter_entidade(table_name, partition_key, row_key):
    client = table_service.get_table_client(table_name)
    e = client.get_entity(partition_key=partition_key, row_key=row_key)
    if table_name == "FelipeProd":
        return normalizar_felipeprod(e)
    if table_name == "FelipeClie":
        return normalizar_felipeclie(e)
    if table_name == "FelipePedi":
        return normalizar_felipepedi(e)
    return dict(e)

def upsert_entidade(table_name, entity):
    """Insere ou atualiza entidade. Lança exceção em caso de erro para não silenciar falhas."""
    # Remove campos internos do Azure que causam erro no upsert
    limpo = {k: v for k, v in entity.items() if not k.startswith("odata.") and k != "Timestamp" and k != "etag"}
    client = table_service.get_table_client(table_name)
    client.upsert_entity(limpo)
    print(f"[Azure Table] upsert OK → {table_name} | PK={limpo.get('PartitionKey')} RK={limpo.get('RowKey')}")

def deletar_entidade(table_name, partition_key, row_key):
    """Deleta entidade. Lança exceção em caso de erro."""
    client = table_service.get_table_client(table_name)
    client.delete_entity(partition_key=partition_key, row_key=row_key)
    print(f"[Azure Table] delete OK → {table_name} | PK={partition_key} RK={row_key}")


# ═══════════════════════════════════════════════════════════════════════════════
# ROTAS — HOME
# ═══════════════════════════════════════════════════════════════════════════════

@app.route("/")
def index():
    felipeprods = listar_entidades("FelipeProd")
    return render_template("index.html", felipeprods=felipeprods)


# ═══════════════════════════════════════════════════════════════════════════════
# ROTAS — FELIPEPRODS
# ═══════════════════════════════════════════════════════════════════════════════

@app.route("/felipeprods")
def felipeprods():
    marca   = request.args.get("marca", "")
    modelo  = request.args.get("modelo", "")
    preco_max = request.args.get("preco_max", "")

    filtros = []
    if marca:
        filtros.append(f"Marca eq '{marca}'")
    if modelo:
        filtros.append(f"Modelo eq '{modelo}'")
    if preco_max:
        filtros.append(f"Valor le {preco_max}")

    filtro_str = " and ".join(filtros) if filtros else None
    lista = listar_entidades("FelipeProd", filtro_str)
    return render_template("felipeprods/lista.html", felipeprods=lista,
                           marca=marca, modelo=modelo, preco_max=preco_max)


@app.route("/felipeprods/novo", methods=["GET", "POST"])
def felipeprod_novo():
    if request.method == "POST":
        try:
            foto_url = ""
            if "foto" in request.files and request.files["foto"].filename:
                foto_url = upload_imagem(request.files["foto"])

            entity = {
                "PartitionKey": "FelipeProd",
                "RowKey":     str(uuid.uuid4()),
                "Marca":      request.form["marca"].strip(),
                "Modelo":     request.form["modelo"].strip(),
                "Valor":      float(request.form["valor"]),
                "Quantidade": int(request.form["quantidade"]),
                "FotoURL":    foto_url,
                "CriadoEm":  datetime.utcnow().isoformat(),
            }
            upsert_entidade("FelipeProd", entity)
            flash("Produto cadastrado com sucesso!", "success")
            return redirect(url_for("felipeprods"))
        except Exception as e:
            print(f"[ERRO felipeprod_novo] {e}")
            flash(f"Erro ao cadastrar felipeprod: {e}", "danger")
    return render_template("felipeprods/form.html", felipeprod=None)


@app.route("/felipeprods/editar/<row_key>", methods=["GET", "POST"])
def felipeprod_editar(row_key):
    felipeprod = obter_entidade("FelipeProd", "FelipeProd", row_key)
    if request.method == "POST":
        try:
            if "foto" in request.files and request.files["foto"].filename:
                felipeprod["FotoURL"] = upload_imagem(request.files["foto"])

            felipeprod["Marca"]      = request.form["marca"].strip()
            felipeprod["Modelo"]     = request.form["modelo"].strip()
            felipeprod["Valor"]      = float(request.form["valor"])
            felipeprod["Quantidade"] = int(request.form["quantidade"])
            upsert_entidade("FelipeProd", felipeprod)
            flash("Produto atualizado com sucesso!", "success")
            return redirect(url_for("felipeprods"))
        except Exception as e:
            print(f"[ERRO felipeprod_editar] {e}")
            flash(f"Erro ao atualizar felipeprod: {e}", "danger")
    return render_template("felipeprods/form.html", felipeprod=felipeprod)


@app.route("/felipeprods/excluir/<row_key>", methods=["POST"])
def felipeprod_excluir(row_key):
    try:
        deletar_entidade("FelipeProd", "FelipeProd", row_key)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "erro": str(e)}), 500


# ═══════════════════════════════════════════════════════════════════════════════
# ROTAS — FELIPECLIES
# ═══════════════════════════════════════════════════════════════════════════════

@app.route("/felipeclies")
def felipeclies():
    lista = listar_entidades("FelipeClie")
    return render_template("felipeclies/lista.html", felipeclies=lista)


@app.route("/felipeclies/novo", methods=["GET", "POST"])
def felipeclie_novo():
    if request.method == "POST":
        try:
            entity = {
                "PartitionKey": "FelipeClie",
                "RowKey":    str(uuid.uuid4()),
                "Nome":      request.form["nome"].strip(),
                "Email":     request.form["email"].strip(),
                "Telefone":  request.form["telefone"].strip(),
                "Endereco":  request.form["endereco"].strip(),
                "CriadoEm": datetime.utcnow().isoformat(),
            }
            upsert_entidade("FelipeClie", entity)
            flash("Cliente cadastrado com sucesso!", "success")
            return redirect(url_for("felipeclies"))
        except Exception as e:
            print(f"[ERRO felipeclie_novo] {e}")
            flash(f"Erro ao cadastrar felipeclie: {e}", "danger")
    return render_template("felipeclies/form.html", felipeclie=None)


@app.route("/felipeclies/editar/<row_key>", methods=["GET", "POST"])
def felipeclie_editar(row_key):
    felipeclie = obter_entidade("FelipeClie", "FelipeClie", row_key)
    if request.method == "POST":
        try:
            felipeclie["Nome"]     = request.form["nome"].strip()
            felipeclie["Email"]    = request.form["email"].strip()
            felipeclie["Telefone"] = request.form["telefone"].strip()
            felipeclie["Endereco"] = request.form["endereco"].strip()
            upsert_entidade("FelipeClie", felipeclie)
            flash("Cliente atualizado com sucesso!", "success")
            return redirect(url_for("felipeclies"))
        except Exception as e:
            print(f"[ERRO felipeclie_editar] {e}")
            flash(f"Erro ao atualizar felipeclie: {e}", "danger")
    return render_template("felipeclies/form.html", felipeclie=felipeclie)


@app.route("/felipeclies/excluir/<row_key>", methods=["POST"])
def felipeclie_excluir(row_key):
    try:
        deletar_entidade("FelipeClie", "FelipeClie", row_key)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "erro": str(e)}), 500


@app.route("/felipeclies/historico/<row_key>")
def felipeclie_historico(row_key):
    felipeclie = obter_entidade("FelipeClie", "FelipeClie", row_key)
    felipepedis = listar_entidades("FelipePedi", f"ClienteId eq '{row_key}'")
    return render_template("felipeclies/historico.html", felipeclie=felipeclie, felipepedis=felipepedis)


# ═══════════════════════════════════════════════════════════════════════════════
# ROTAS — CHECKOUT / FELIPEPEDIS
# ═══════════════════════════════════════════════════════════════════════════════

@app.route("/checkout", methods=["GET", "POST"])
def checkout():
    felipeprods = listar_entidades("FelipeProd")
    felipeclies = listar_entidades("FelipeClie")

    if request.method == "POST":
        try:
            produto_id = request.form["produto_id"]
            cliente_id = request.form["cliente_id"]
            quantidade = int(request.form["quantidade"])
            pagamento  = request.form["pagamento"]
            entrega    = request.form["entrega"]

            felipeprod = obter_entidade("FelipeProd", "FelipeProd", produto_id)

            # Validações
            if quantidade <= 0:
                flash("Quantidade deve ser maior que zero.", "danger")
                return render_template("checkout.html", felipeprods=felipeprods, felipeclies=felipeclies)
            if quantidade > felipeprod["Quantidade"]:
                flash(f"Estoque insuficiente. Disponível: {felipeprod['Quantidade']}", "danger")
                return render_template("checkout.html", felipeprods=felipeprods, felipeclies=felipeclies)

            total = felipeprod["Valor"] * quantidade

            # Salva felipepedi
            felipepedi = {
                "PartitionKey": "FelipePedi",
                "RowKey":       str(uuid.uuid4()),
                "ClienteId":    cliente_id,
                "ProdutoId":    produto_id,
                "ProdutoNome":  f"{felipeprod['Marca']} {felipeprod['Modelo']}",
                "Quantidade":   quantidade,
                "Total":        total,
                "Pagamento":    pagamento,
                "Entrega":      entrega,
                "Status":       "Confirmado",
                "CriadoEm":     datetime.utcnow().isoformat(),
            }
            upsert_entidade("FelipePedi", felipepedi)

            # Atualiza estoque
            felipeprod["Quantidade"] -= quantidade
            upsert_entidade("FelipeProd", felipeprod)

            flash(f"Pedido realizado! Total: R$ {total:.2f}", "success")
            return redirect(url_for("index"))
        except Exception as e:
            print(f"[ERRO checkout] {e}")
            flash(f"Erro ao processar felipepedi: {e}", "danger")

    return render_template("checkout.html", felipeprods=felipeprods, felipeclies=felipeclies)


# ═══════════════════════════════════════════════════════════════════════════════
# ROTAS — FELIPEPEDIS
# ═══════════════════════════════════════════════════════════════════════════════

@app.route("/felipepedis")
def felipepedis():
    lista = listar_entidades("FelipePedi")
    return render_template("felipepedis.html", felipepedis=lista)


if __name__ == "__main__":
    app.run(debug=True)
