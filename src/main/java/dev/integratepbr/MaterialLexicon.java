package dev.integratepbr;

import java.util.Collection;
import java.util.HashMap;
import java.util.HashSet;
import java.util.Locale;
import java.util.Map;
import java.util.Set;

/** Learns probable material families from naming patterns within each installed mod. */
public final class MaterialLexicon {
    private static final Set<String> CONTEXT = Set.of("ingot", "ingots", "nugget", "nuggets", "ore", "ores");
    private static final Set<String> STONE_BASE = Set.of("stone", "rock", "cobblestone", "cobble");
    private static final Set<String> STONE_FORM = Set.of("brick", "bricks", "tile", "tiles",
            "stairs", "slab", "wall", "pillar", "polished");
    private static final Set<String> NON_MATERIAL = Set.of("raw", "refined", "crushed", "tiny", "small",
            "large", "chunk", "dense", "rich", "poor", "deepslate", "nether", "end", "block",
            "dust", "piece", "shard", "gem", "item", "mod", "netherite", "stone", "wood");
    private final Map<String, Set<String>> metalsByNamespace;
    private final Map<String, Set<String>> woodsByNamespace;
    private final Map<String, Set<String>> stonesByNamespace;

    private MaterialLexicon(Map<String, Set<String>> metalsByNamespace, Map<String, Set<String>> woodsByNamespace,
                            Map<String, Set<String>> stonesByNamespace) {
        this.metalsByNamespace = metalsByNamespace;
        this.woodsByNamespace = woodsByNamespace;
        this.stonesByNamespace = stonesByNamespace;
    }

    public static MaterialLexicon learn(Collection<String> registeredIds) {
        Map<String, Map<String, Evidence>> evidence = new HashMap<>();
        Map<String, Map<String, StoneEvidence>> stoneEvidence = new HashMap<>();
        Map<String, Set<String>> woods = new HashMap<>();
        for (String id : new HashSet<>(registeredIds)) {
            int colon = id.indexOf(':');
            if (colon < 1 || colon == id.length() - 1) continue;
            String namespace = id.substring(0, colon);
            String[] words = id.substring(colon + 1).toLowerCase(Locale.ROOT).split("[^a-z0-9]+");
            for (int index = 0; index < words.length; index++) {
                if (!words[index].equals("sapling")) continue;
                String tree = index == 0 && words.length > 1 ? words[1]
                        : String.join("_", java.util.Arrays.copyOfRange(words, 0, index));
                if (tree.length() >= 3 && !NON_MATERIAL.contains(tree))
                    woods.computeIfAbsent(namespace, unused -> new HashSet<>()).add(tree);
            }
            for (int index = 0; index < words.length; index++) {
                String context = words[index];
                if (!STONE_BASE.contains(context) && !STONE_FORM.contains(context)) continue;
                String candidate = index == 0 && words.length > 1 ? words[1] : words[index - 1];
                if (candidate.length() < 3 || NON_MATERIAL.contains(candidate)
                        || STONE_BASE.contains(candidate) || STONE_FORM.contains(candidate)) continue;
                StoneEvidence found = stoneEvidence.computeIfAbsent(namespace, unused -> new HashMap<>())
                        .computeIfAbsent(candidate, unused -> new StoneEvidence());
                if (STONE_BASE.contains(context)) found.base = true;
                else found.form = true;
            }
            for (int index = 0; index < words.length; index++) {
                if (!CONTEXT.contains(words[index])) continue;
                String candidate = index == 0 && words.length > 1 ? words[1] : words[index - 1];
                if (candidate.length() < 3 || NON_MATERIAL.contains(candidate) || CONTEXT.contains(candidate)) continue;
                Evidence found = evidence.computeIfAbsent(namespace, unused -> new HashMap<>())
                        .computeIfAbsent(candidate, unused -> new Evidence());
                if (words[index].startsWith("ore")) found.ore = true;
                else if (words[index].startsWith("nugget")) found.nugget = true;
                else found.ingot = true;
            }
        }
        Map<String, Set<String>> learned = new HashMap<>();
        evidence.forEach((namespace, terms) -> {
            Set<String> accepted = new HashSet<>();
            terms.forEach((term, found) -> {
                if ((found.ingot || found.nugget) && found.score() >= 3) accepted.add(term);
            });
            learned.put(namespace, Set.copyOf(accepted));
        });
        Map<String, Set<String>> frozenWoods = new HashMap<>();
        woods.forEach((namespace, terms) -> frozenWoods.put(namespace, Set.copyOf(terms)));
        Map<String, Set<String>> stones = new HashMap<>();
        stoneEvidence.forEach((namespace, terms) -> {
            Set<String> accepted = new HashSet<>();
            terms.forEach((term, found) -> { if (found.base && found.form) accepted.add(term); });
            stones.put(namespace, Set.copyOf(accepted));
        });
        return new MaterialLexicon(Map.copyOf(learned), Map.copyOf(frozenWoods), Map.copyOf(stones));
    }

    public String matchingMetalTerm(String namespace, String name) {
        return matching(metalsByNamespace, namespace, name);
    }

    public String matchingWoodTerm(String namespace, String name) {
        return matching(woodsByNamespace, namespace, name);
    }

    public String matchingStoneTerm(String namespace, String name) {
        return matching(stonesByNamespace, namespace, name);
    }

    private static String matching(Map<String, Set<String>> groups, String namespace, String name) {
        String words = "_" + name.toLowerCase(Locale.ROOT).replaceAll("[^a-z0-9]+", "_") + "_";
        return groups.getOrDefault(namespace, Set.of()).stream().sorted()
                .filter(term -> words.contains("_" + term + "_"))
                .findFirst().orElse(null);
    }

    private static final class Evidence {
        boolean ingot, nugget, ore;
        int score() { return (ingot ? 2 : 0) + (nugget ? 2 : 0) + (ore ? 1 : 0); }
    }

    private static final class StoneEvidence {
        boolean base, form;
    }
}
