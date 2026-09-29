package dev.integratepbr;

import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.resources.ResourceLocation;
import net.minecraft.server.packs.resources.ResourceManager;
import net.neoforged.fml.ModList;

import java.io.IOException;
import java.util.HashMap;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.Map;
import java.util.Set;

/** Finds texture references in ordinary item models and blockstate/model JSON. */
public final class ModelTextureIndex {
    public record Owner(MaterialOverrides.Kind kind, ResourceLocation id) {}
    private final ResourceManager resources;
    private final Map<ResourceLocation, JsonObject> jsonCache = new HashMap<>();
    private final Map<ResourceLocation, ModelData> modelCache = new HashMap<>();
    private final Map<ResourceLocation, Set<Owner>> ownersByTexture = new LinkedHashMap<>();

    private record ModelData(Map<String, String> textures, Set<ResourceLocation> children) {}
    private ModelTextureIndex(ResourceManager resources) { this.resources = resources; }

    public static Map<ResourceLocation, Set<Owner>> scan(ResourceManager resources) {
        ModelTextureIndex index = new ModelTextureIndex(resources);
        for (ResourceLocation id : BuiltInRegistries.ITEM.keySet()) {
            if (index.isContentMod(id)) index.scanOwner(new Owner(MaterialOverrides.Kind.ITEM, id));
        }
        for (ResourceLocation id : BuiltInRegistries.BLOCK.keySet()) {
            if (index.isContentMod(id)) index.scanOwner(new Owner(MaterialOverrides.Kind.BLOCK, id));
        }
        return index.ownersByTexture;
    }

    private boolean isContentMod(ResourceLocation id) {
        return !id.getNamespace().equals("minecraft") && !id.getNamespace().equals(IntegratePbr.MOD_ID)
                && ModList.get().isLoaded(id.getNamespace());
    }

    private void scanOwner(Owner owner) {
        ResourceLocation id = owner.id();
        if (owner.kind() == MaterialOverrides.Kind.ITEM) {
            ResourceLocation model = ResourceLocation.fromNamespaceAndPath(id.getNamespace(), "models/item/" + id.getPath() + ".json");
            collectModelTextures(model, owner, new HashSet<>());
            collectArmorTextures(owner);
        } else {
            ResourceLocation state = ResourceLocation.fromNamespaceAndPath(id.getNamespace(), "blockstates/" + id.getPath() + ".json");
            JsonObject json = readJson(state);
            if (json == null) return;
            Set<ResourceLocation> models = new LinkedHashSet<>();
            findModelReferences(json, models);
            for (ResourceLocation model : models) {
                collectModelTextures(modelPath(model), owner, new HashSet<>());
            }
        }
    }

    /** Armor layers are rendered separately from item icons and have no JSON model references. */
    private void collectArmorTextures(Owner owner) {
        String path = owner.id().getPath();
        for (String suffix : new String[] {"_helmet", "_chestplate", "_leggings", "_boots"}) {
            if (!path.endsWith(suffix)) continue;
            String prefix = path.substring(0, path.length() - suffix.length());
            for (int layer = 1; layer <= 2; layer++) {
                ResourceLocation texture = ResourceLocation.fromNamespaceAndPath(owner.id().getNamespace(),
                        "textures/models/armor/" + prefix + "_layer_" + layer + ".png");
                if (resources.getResource(texture).isPresent()) {
                    ownersByTexture.computeIfAbsent(texture, unused -> new LinkedHashSet<>()).add(owner);
                }
            }
            return;
        }
    }

    private void collectModelTextures(ResourceLocation modelFile, Owner owner, Set<ResourceLocation> visiting) {
        if (!visiting.add(modelFile)) return;
        ModelData data = readModel(modelFile, new HashSet<>());
        if (data == null) return;
        for (String value : data.textures().values()) {
            String resolved = resolve(value, data.textures(), new HashSet<>());
            if (resolved == null) continue;
            try {
                ResourceLocation texture = ResourceLocation.parse(resolved);
                if (texture.getNamespace().equals("minecraft") || texture.getPath().endsWith("_n")
                        || texture.getPath().endsWith("_s")) continue;
                ResourceLocation png = ResourceLocation.fromNamespaceAndPath(texture.getNamespace(),
                        "textures/" + texture.getPath() + ".png");
                if (resources.getResource(png).isPresent()) {
                    ownersByTexture.computeIfAbsent(png, unused -> new LinkedHashSet<>()).add(owner);
                }
            } catch (RuntimeException ignored) { /* Invalid model reference. */ }
        }
        for (ResourceLocation child : data.children()) collectModelTextures(modelPath(child), owner, visiting);
    }

    private ModelData readModel(ResourceLocation file, Set<ResourceLocation> visiting) {
        ModelData cached = modelCache.get(file);
        if (cached != null) return cached;
        if (!visiting.add(file)) return null;
        JsonObject json = readJson(file);
        if (json == null) { visiting.remove(file); return null; }
        Map<String, String> textures = new LinkedHashMap<>();
        Set<ResourceLocation> children = new LinkedHashSet<>();
        if (json.has("parent") && json.get("parent").isJsonPrimitive()) {
            try {
                ModelData parent = readModel(modelPath(ResourceLocation.parse(json.get("parent").getAsString())), visiting);
                if (parent != null) textures.putAll(parent.textures());
            } catch (RuntimeException ignored) { /* Invalid parent. */ }
        }
        if (json.has("textures") && json.get("textures").isJsonObject()) {
            for (var entry : json.getAsJsonObject("textures").entrySet()) {
                if (entry.getValue().isJsonPrimitive()) textures.put(entry.getKey(), entry.getValue().getAsString());
            }
        }
        if (json.has("overrides")) findModelReferences(json.get("overrides"), children);
        ModelData data = new ModelData(Map.copyOf(textures), Set.copyOf(children));
        modelCache.put(file, data);
        visiting.remove(file);
        return data;
    }

    private static String resolve(String value, Map<String, String> textures, Set<String> visiting) {
        if (!value.startsWith("#")) return value;
        String key = value.substring(1);
        if (!visiting.add(key)) return null;
        String next = textures.get(key);
        return next == null ? null : resolve(next, textures, visiting);
    }

    private JsonObject readJson(ResourceLocation file) {
        if (jsonCache.containsKey(file)) return jsonCache.get(file);
        JsonObject result = null;
        var resource = resources.getResource(file);
        if (resource.isPresent()) {
            try (var reader = resource.get().openAsReader()) {
                JsonElement parsed = JsonParser.parseReader(reader);
                if (parsed.isJsonObject()) result = parsed.getAsJsonObject();
            } catch (IOException | RuntimeException ignored) { /* Custom or malformed model. */ }
        }
        jsonCache.put(file, result);
        return result;
    }

    private static void findModelReferences(JsonElement element, Set<ResourceLocation> result) {
        if (element.isJsonObject()) {
            for (var entry : element.getAsJsonObject().entrySet()) {
                if (entry.getKey().equals("model") && entry.getValue().isJsonPrimitive()) {
                    try { result.add(ResourceLocation.parse(entry.getValue().getAsString())); }
                    catch (RuntimeException ignored) { /* Invalid path. */ }
                } else findModelReferences(entry.getValue(), result);
            }
        } else if (element.isJsonArray()) {
            for (JsonElement child : element.getAsJsonArray()) findModelReferences(child, result);
        }
    }

    private static ResourceLocation modelPath(ResourceLocation model) {
        return ResourceLocation.fromNamespaceAndPath(model.getNamespace(), "models/" + model.getPath() + ".json");
    }
}
