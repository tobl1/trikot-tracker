# Wird über BASH_ENV in jeden run-Schritt von tracker.yml geladen.
# git push mit Wiederholung: GitHub antwortet gelegentlich mit "Internal Server Error" (07.10.2026)
pushen() {
  for i in 1 2 3 4 5; do
    git push -q "$@" && return 0
    echo "Push fehlgeschlagen (Versuch $i von 5), neuer Versuch in $((i * 15)) s"
    sleep $((i * 15))
  done
  return 1
}
