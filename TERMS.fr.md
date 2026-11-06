# Conditions d'utilisation et de partage de XeryusCrawl

En installant ou en utilisant XeryusCrawl, vous acceptez sa licence ([LICENSE.md](LICENSE.md), PolyForm Noncommercial 1.0.0)
et les présentes conditions. English: [TERMS.md](TERMS.md).

## 1. Utiliser XeryusCrawl

- Vous utilisez XeryusCrawl sur votre propre ordinateur et êtes responsable de ce que vous lisez, parcourez et conservez avec
  lui, y compris le respect des conditions des sites Web, du droit d'auteur et des lois de votre lieu de résidence. Par défaut,
  il respecte le fichier robots.txt et garde un rythme courtois.
- Le mode furtif (désactivé sauf si vous l'activez) ne doit pas servir à contourner une connexion, un accès payant ou le refus
  explicite d'un site Web.
- XeryusCrawl est fourni tel quel, sans garantie, dans la mesure permise par la loi.
- Si vous utilisez un fournisseur d'IA infonuagique ou Brave Search, vos requêtes lui sont envoyées selon ses propres
  conditions, avec votre propre clé.

## 2. Partage de passages de recherche (seulement si vous acceptez)

**Le partage est désactivé tant que vous ne l'activez pas.** `xeryuscrawl setup` vous le demande une fois; vous pouvez
changer d'avis en tout temps avec `xeryuscrawl sharing on` ou `xeryuscrawl sharing off`. Rien n'est partagé avant votre
accord, et le désactiver supprime tout ce qui attendait d'être envoyé.

**Qui le reçoit.** myMAK.ai, Oakville (Ontario), Canada (le responsable du traitement). Pour joindre notre responsable de la
protection des renseignements personnels : support@mymak.ai.

**Ce qui est partagé.** Lorsque vous lancez une recherche approfondie, les passages Web publics qu'elle trouve : le texte de
chaque passage, son adresse Web et le titre de la page. Avant toute conservation, les adresses courriel, numéros de téléphone,
longs numéros et ce qui ressemble à des clés sont masqués. Un identifiant d'installation aléatoire les accompagne; myMAK.ai
n'en conserve qu'une empreinte à sens unique, servant à appliquer des limites quotidiennes.

**Ce qui n'est jamais partagé.** Vos questions, recherches et réponses, vos clés d'API, vos fichiers, les pages que vous lisez
hors de la recherche approfondie, et tout autre contenu de votre ordinateur. myMAK.ai ne conserve pas votre adresse IP avec ce
que vous partagez.

**Pourquoi.** Pour entraîner et améliorer des modèles d'IA de myMAK.ai, qui peuvent servir dans ses produits, y compris des
produits payants. Le fondement juridique est votre consentement, que vous pouvez retirer en tout temps.

**Traitement.** Les passages sont envoyés au plus une fois par jour, par une connexion chiffrée, à la base de données de
myMAK.ai (Supabase). myMAK.ai les recueille chaque semaine, vérifie chacun auprès de sa page d'origine, retire les doublons et
masque de nouveau les renseignements personnels, puis les supprime de cette base; ce qui n'est pas recueilli est supprimé
après 30 jours. Un passage déjà utilisé pour entraîner un modèle ne peut pas en être retiré, mais il s'agit de texte Web
public, et non de renseignements sur vous.

**Vos droits.** Selon votre lieu de résidence (notamment le Québec, le reste du Canada, l'UE et le Royaume-Uni, et la
Californie), vous pouvez demander l'accès à des renseignements vous concernant, leur rectification ou leur suppression, ou
porter plainte auprès de votre autorité de protection des données. Comme ce que vous partagez est du texte Web public lié
seulement à un identifiant aléatoire, joignez votre identifiant d'installation (dans `~/.xeryuscrawl/config.json`) à toute
demande envoyée à support@mymak.ai.

## 3. Modifications

Si ces conditions changent, la nouvelle version est publiée ici avec sa date. Tout changement à ce qui est partagé ou à la
raison du partage vous sera demandé de nouveau avant de s'appliquer.

Version 1, 2026-11-06.
