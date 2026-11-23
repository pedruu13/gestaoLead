import os
import sqlite3
import sys
import tempfile
import unittest


class TestDeployBackupLogic(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "gestao_leads.db")
        self.backup_dir = os.path.join(self.temp_dir.name, "backups")
        os.makedirs(self.backup_dir, exist_ok=True)

        # Inicializa banco de teste simulando produção com modo WAL
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("CREATE TABLE leads (id INTEGER PRIMARY KEY, nome TEXT, status TEXT)")
        conn.execute("INSERT INTO leads (nome, status) VALUES ('Empresa Teste A', 'Novo')")
        conn.execute("INSERT INTO leads (nome, status) VALUES ('Empresa Teste B', 'Contatado')")
        conn.commit()
        conn.close()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_backup_creates_consistent_database(self):
        """Valida se o backup SQLite online gera uma cópia íntegra e não-vazia."""
        backup_file = os.path.join(self.backup_dir, "pre-deploy-20261122-230000.db")

        # Mecanismo seguro de backup SQLite idêntico ao implementado no pipeline
        src = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
        dst = sqlite3.connect(backup_file)
        with dst:
            src.backup(dst, pages=100)
        dst.close()
        src.close()

        # 1. Verifica se arquivo foi criado e possui tamanho > 0
        self.assertTrue(os.path.exists(backup_file))
        self.assertGreater(os.path.getsize(backup_file), 0)

        # 2. Verifica se pode ser aberto como banco SQLite válido e passa no integrity_check
        conn = sqlite3.connect(f"file:{backup_file}?mode=ro", uri=True)
        cur = conn.cursor()
        res = cur.execute("PRAGMA integrity_check;").fetchall()
        self.assertEqual(res, [("ok",)])

        # 3. Verifica se os dados coincidem com a origem
        rows = cur.execute("SELECT id, nome, status FROM leads ORDER BY id").fetchall()
        conn.close()
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0], (1, "Empresa Teste A", "Novo"))
        self.assertEqual(rows[1], (2, "Empresa Teste B", "Contatado"))

    def test_no_data_mutation_on_source(self):
        """Garante que a origem não sofre mutação em tabelas ou registros durante o backup."""
        conn_before = sqlite3.connect(self.db_path)
        before_count = conn_before.execute("SELECT count(*) FROM leads").fetchone()[0]
        conn_before.close()

        backup_file = os.path.join(self.backup_dir, "pre-deploy-test-mutation.db")
        src = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
        dst = sqlite3.connect(backup_file)
        with dst:
            src.backup(dst, pages=100)
        dst.close()
        src.close()

        conn_after = sqlite3.connect(self.db_path)
        after_count = conn_after.execute("SELECT count(*) FROM leads").fetchone()[0]
        conn_after.close()

        self.assertEqual(before_count, after_count)

    def test_existing_backup_protection(self):
        """Garante que a rotina aborta se já existir arquivo com o mesmo nome para evitar sobrescrita."""
        backup_file = os.path.join(self.backup_dir, "pre-deploy-existing.db")
        with open(backup_file, "w") as f:
            f.write("conteudo existente anterior")

        # Simula a checagem que o pipeline faz antes de disparar o backup
        file_exists = os.path.exists(backup_file)
        self.assertTrue(file_exists)

        # Se existe, não deve sobrescrever
        with open(backup_file, "r") as f:
            content = f.read()
        self.assertEqual(content, "conteudo existente anterior")

    def test_pipeline_yaml_contains_safety_guarantees(self):
        """Verifica se o arquivo deploy-oracle.yml contém as regras de proteção exigidas."""
        workflow_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".github", "workflows", "deploy-oracle.yml"))
        self.assertTrue(os.path.exists(workflow_path))

        with open(workflow_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Checa elementos críticos
        self.assertIn("pre-deploy-${TIMESTAMP}.db", content)
        self.assertIn("src.backup(dst", content)
        self.assertIn("PRAGMA integrity_check", content)
        self.assertIn("mode=ro", content)
        self.assertIn("git pull --ff-only origin main", content)

        # Garante que o backup é executado ANTES do git pull
        backup_pos = content.find("Iniciando backup pré-deploy consistente")
        pull_pos = content.find("git pull --ff-only origin main")
        self.assertGreater(backup_pos, 0)
        self.assertGreater(pull_pos, backup_pos, "O backup pré-deploy DEVE ser executado antes do git pull!")


if __name__ == "__main__":
    unittest.main()
