# Fermeture école Québec — intégration Home Assistant

Intégration personnalisée qui suit les fermetures d'écoles **du Québec**
annoncées par [TVA Nouvelles](https://www.tvanouvelles.ca/ecoles-fermees) et les
expose comme un appareil Home Assistant par école.

Elle remplace le [package YAML `fermeture-ecoles`](https://github.com/domo-quebec/fermeture-ecoles)
tout en conservant ses attributs (`message`, `information`) et ses états
(`Fermée` / `Ouverte`), donc les cartes Lovelace existantes continuent de
fonctionner.

## Sources de données

| Endpoint | Usage |
| --- | --- |
| `https://www.tvanouvelles.ca/api/schools/list` | Liste des écoles (id, nom, ville) pour le config flow |
| `https://www.tvanouvelles.ca/api/schools/closed` | Fermetures en cours (une seule requête partagée par toutes les écoles) |

Les données sont fournies par TVA Nouvelles et peuvent comporter des erreurs :
en cas de doute, vérifiez le site officiel de votre centre de services scolaire.

## Installation

> Nécessite Home Assistant **2025.8** ou plus récent (Python 3.13).

### HACS (dépôt personnalisé)

1. HACS → Intégrations → menu ⋮ → *Dépôts personnalisés*.
2. Ajouter `domo-quebec/fermeture-ecole-quebec-ha` en catégorie *Integration*.
3. Installer, puis redémarrer Home Assistant.

### Manuelle

Copier `custom_components/fermeture_ecole_quebec` dans le dossier
`config/custom_components/` de Home Assistant, puis redémarrer.

### Configuration

*Paramètres → Appareils et services → Ajouter une intégration →
« Fermeture école Québec ».*

1. Recherchez l'école par **nom ou ville** (la recherche ignore les accents et
   la casse). Le champ « Saisir l'identifiant manuellement » permet d'utiliser
   un id de la [liste officielle](https://github.com/domo-quebec/fermeture-ecoles/blob/main/list.md)
   si l'API est indisponible.
2. Sélectionnez l'école dans la liste des résultats.
3. Répétez l'opération pour chaque école à surveiller : chaque école est un
   appareil distinct, avec ses propres entités.

## Horaire de rafraîchissement

Le rafraîchissement n'est **pas** une simple interrogation périodique : chaque
école reçoit un horaire aléatoire, propre à son entrée de configuration.

| Période | Jours | Comportement |
| --- | --- | --- |
| Matin (05:00 → 08:00) | Lundi → vendredi | Un rafraîchissement toutes les **15 à 20 minutes**, premier passage décalé aléatoirement jusqu'à 10 minutes après 05:00 |
| Soir (17:00 → 21:00) | Dimanche → jeudi | **Un seul** rafraîchissement, à une heure aléatoire |
| Hors saison (mai → septembre par défaut) | — | Aucun rafraîchissement ; la reprise est déjà planifiée pour le premier créneau de la saison suivante |
| Démarrage de Home Assistant | — | Un rafraîchissement initial immédiat ; si l'API échoue, Home Assistant relance la configuration avec un délai croissant |

Pourquoi ces choix :

* **Anti-rafale** : l'horaire est généré à partir d'une graine stable
  `entrée + école + date`. Il est donc identique après un redémarrage, mais
  différent pour chaque installation et chaque jour — tout le monde ne frappe
  pas l'API à 05:00:00 pile.
* **Une requête par cycle** : toutes les écoles d'une même instance Home
  Assistant partagent un cache de 90 secondes, donc 5 écoles ne coûtent pas
  5 requêtes.
* **Soir** : un seul passage, car les fermetures du lendemain sont annoncées en
  soirée. Le dimanche soir est inclus (annonce pour le lundi).
* **Aucune requête inutile** : pas de rafraîchissement la fin de semaine, ni
  hors saison, ni pendant les congés si vous configurez une entité `workday`.

L'horaire est visible par entité (capteur diagnostique *Prochaine mise à jour*)
et dans les diagnostics de l'intégration.

## Entités

Chaque école crée un appareil avec :

| Entité | Type | Description |
| --- | --- | --- |
| `sensor.<ecole>_fermeture` | Capteur | État `Fermée` ou `Ouverte` |
| `binary_sensor.<ecole>_fermeture_en_cours` | Capteur binaire | `on` pendant une fermeture (pratique pour les automatisations) |
| `sensor.<ecole>_derniere_mise_a_jour` | Diagnostic | Heure du dernier rafraîchissement réussi |
| `sensor.<ecole>_prochaine_mise_a_jour` | Diagnostic | Heure du prochain rafraîchissement planifié |
| `button.<ecole>_rafraichir_maintenant` | Configuration | Force un rafraîchissement immédiat |

> Les noms d'entités ci-dessus correspondent à une instance en français
> (`closure`, `last_update`, `next_update`, `closure_active`, `refresh` en
> anglais). L'`entity_id` est figé à la création de l'entité : consultez
> *Paramètres → Appareils et services → Entités* pour le nom exact.

### Attributs du capteur de fermeture

| Attribut | Description |
| --- | --- |
| `message` | Message libre de TVA (compatibilité package YAML) |
| `information` | Liste des informations (`Cours suspendus`, `Pas de transport`…) (compatibilité package YAML) |
| `school_id`, `school_name`, `town`, `region`, `school_board` | Identification de l'école |
| `closure_state` | État brut de la fermeture (`closed`) |
| `closure_start`, `closure_end` | Fenêtre de la fermeture (ISO 8601) |
| `last_updated`, `last_updated_raw` | Horodatage du document API |
| `next_refresh` | Prochain rafraîchissement planifié |
| `attribution` | Source des données |

Une fermeture est considérée active lorsque `datetime_start <= maintenant <=
datetime_end`. Si `datetime_end` est absent, la fermeture est considérée
ouverte (comme le fait TVA pour une fermeture « jusqu'à nouvel ordre »).

## Service `fermeture_ecole_quebec.refresh`

Force une mise à jour immédiate. La cible peut être une entité **ou** un
appareil.

```yaml
action: fermeture_ecole_quebec.refresh
target:
  entity_id: sensor.ecole_bonnier_mercier_fermeture
data:
  force: true   # défaut : contourne le cache partagé de 90 s
response_variable: resultat
```

La réponse contient les données de chaque école ciblée (`response_variable` est
optionnel : sans lui, le service ne retourne rien) :

```yaml
schools:
  - school_id: 1274
    name: Bonnier
    closed: true
    message: "Le mardi 5 décembre, pour la journée"
    information:
      - Pas de transport pour la journée
    next_refresh: "2026-12-05T06:12:44-05:00"
failed: []
```

### Automatisation d'exemple

```yaml
alias: École fermée ce matin
triggers:
  - trigger: state
    entity_id: binary_sensor.ecole_bonnier_mercier_fermeture_en_cours
    to: "on"
actions:
  - action: notify.mobile_app
    data:
      title: École fermée
      message: >-
        {{ state_attr('sensor.ecole_bonnier_mercier_fermeture', 'message')
           or 'Fermeture annoncée' }}
```

## Options

*Paramètres → Appareils et services → Fermeture école Québec → Configurer.*

| Option | Défaut | Description |
| --- | --- | --- |
| Limiter à la saison scolaire | Activé | Désactiver pour rafraîchir toute l'année |
| Mois de la saison | Oct → Avr | Mois pendant lesquels les rafraîchissements ont lieu |
| Fenêtre du matin | 05:00 → 08:00 | Plage des rafraîchissements répétés |
| Intervalle min / max | 15 / 20 min | Bornes de l'intervalle aléatoire |
| Rafraîchir le soir | Activé | Un passage aléatoire entre 17:00 et 21:00 |
| Fenêtre du soir | 17:00 → 21:00 | Plage du passage unique |
| Entité jour ouvrable | — | Si `off`, aucun rafraîchissement le matin (congés, journée pédagogique). Ex. `binary_sensor.workday_sensor` |
| Surveiller une autre école | — | Change l'école associée à l'entrée |

L'option « Entité jour ouvrable » accepte un `binary_sensor` ou un
`input_boolean` (par exemple celui de l'intégration
[Workday](https://www.home-assistant.io/integrations/workday/)). Si l'entité
est `unknown` ou `unavailable`, le rafraîchissement a lieu quand même.

## Compatibilité avec les cartes Lovelace existantes

Les cartes du dépôt `fermeture-ecoles` utilisent :

```jinja
{{ states('sensor.nom_ecole') }}
{{ state_attr('sensor.nom_ecole', 'message') }}
{{ state_attr('sensor.nom_ecole', 'information') }}
```

Adaptez uniquement l'`entity_id` vers la nouvelle entité de fermeture ; les
attributs et les valeurs (`Fermée` / `Ouverte`) sont identiques. L'attribut
`icon` n'est plus `mdi:town-hall` mais `mdi:school` / `mdi:school-off`.

## Dépannage

* **Capteurs indisponibles au démarrage** : l'API TVA est peut-être
  inaccessible. Home Assistant relance automatiquement la configuration avec un
  délai croissant ; les entités apparaissent dès que l'API répond. Pour un
  échec plus tardif, l'intégration retente deux fois dans les minutes qui
  suivent, puis reprend l'horaire normal.
* **Diagnostics** : *Paramètres → Appareils et services → Fermeture école Québec →
  ⋮ → Télécharger les diagnostics* (horaire, prochains créneaux, dernière
  fermeture connue).
* **Aucun rafraîchissement** : vérifiez le mois (saison), le jour de la semaine
  et l'entité jour ouvrable. Le capteur *Prochaine mise à jour* montre le
  prochain créneau planifié.
* **Journée pédagogique non détectée** : ajoutez une entité `workday` adaptée
  dans les options.

## Développement

```bash
python -m venv .venv
.venv/bin/pip install -r requirements_test.txt
.venv/bin/pytest -q
.venv/bin/ruff check .
.venv/bin/ruff format --check .
```

## Licence

MIT — voir [LICENSE](LICENSE). Données : © TVA Nouvelles.
