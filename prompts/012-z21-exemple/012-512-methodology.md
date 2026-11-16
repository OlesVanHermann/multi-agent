# 012-512 Methodology — Tester

1. Lire la commande de test dans `{ctx}/methodology.md` section "Tests"
2. Lancer en isolation : `cd $BASE && python -m pytest {test_file} -v`
3. En cas d'échec : capturer le message d'erreur exact (pas juste "fail")
4. Distinguer : test fonctionnel vs erreur d'infrastructure (Redis down, DB absente)
