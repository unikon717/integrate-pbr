package dev.integratepbr.model.discovery;

import dev.integratepbr.model.discovery.ResourceSnapshot.Owner;

import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import net.minecraft.resources.ResourceLocation;

import java.io.IOException;
import java.util.HashMap;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.Map;
import java.util.Set;

/** Finds texture references in ordinary item models and blockstate/model JSON. */
final class ModelResourceIndex {
    private final ResourceSnapshot.Access snapshotAccess;
    private final ResourceSnapshot.Limits snapshotLimits;
    private Owner currentOwner;
    private int jsonReads;
    private long jsonBytes;
    private final Set<ResourceLocation> snapshotProcessed = new HashSet<>();
    private final java.util.List<ResourceSnapshot.Omission> omissions = new java.util.ArrayList<>();
    private final Map<ResourceLocation, java.util.List<ResourceSnapshot.Evidence>> evidence = new LinkedHashMap<>();
    record SourceDocument(ResourceLocation id, String provider, byte[] bytes) {
        public SourceDocument { bytes=bytes.clone(); }
        @Override public byte[] bytes(){return bytes.clone();}
    }
    private final Map<ResourceLocation,SourceDocument> sourceDocuments = new LinkedHashMap<>();
    record SnapshotDiscovery(Map<ResourceLocation, Set<Owner>> textures,
            Map<ResourceLocation, java.util.List<ResourceSnapshot.Evidence>> evidence,
            java.util.List<ResourceSnapshot.Omission> omissions, int ownerCount, java.util.List<SourceDocument> documents) {}
    static SnapshotDiscovery snapshotScan(Iterable<Owner> owners, ResourceSnapshot.Access access, ResourceSnapshot.Limits limits) {
        ModelResourceIndex index = new ModelResourceIndex(access, limits);
        int count = 0;
        for (Owner owner : owners) {
            if (++count > limits.owners()) { index.omit("owner_limit", null, "registry owner bound reached"); break; }
            index.currentOwner = owner;
            index.scanOwner(owner);
        }
        return new SnapshotDiscovery(index.ownersByTexture, index.evidence, index.omissions, Math.min(count, limits.owners()), java.util.List.copyOf(index.sourceDocuments.values()));
    }
    private void omit(String kind, ResourceLocation resource, String detail) {
        omissions.add(new ResourceSnapshot.Omission(kind, currentOwner, resource, detail));
    }
    private boolean present(ResourceLocation id) {
        try { return ResourceSnapshot.external(snapshotAccess.stack(id)) != null; }
        catch (IOException e) { omit("resource_error", id, e.toString()); return false; }
    }
    private void addTexture(ResourceLocation texture, Owner owner, String kind, ResourceLocation reference) {
        ownersByTexture.computeIfAbsent(texture, unused -> new LinkedHashSet<>()).add(owner);
        evidence.computeIfAbsent(texture, unused -> new java.util.ArrayList<>()).add(new ResourceSnapshot.Evidence(kind, owner, reference));
    }
    private final Map<ResourceLocation, JsonObject> jsonCache = new HashMap<>();
    private final Map<ResourceLocation, ModelData> modelCache = new HashMap<>();
    private final Map<ResourceLocation, Set<Owner>> ownersByTexture = new LinkedHashMap<>();

    private record ModelData(Map<String, String> textures, Set<ResourceLocation> children) {}
    private ModelResourceIndex(ResourceSnapshot.Access access, ResourceSnapshot.Limits limits) {
        this.snapshotAccess = java.util.Objects.requireNonNull(access);
        this.snapshotLimits = java.util.Objects.requireNonNull(limits);
    }

    private void scanOwner(Owner owner) {
        snapshotProcessed.clear();
        ResourceLocation id = owner.id();
        if (owner.kind() == ResourceSnapshot.Kind.ITEM) {
            ResourceLocation model = ResourceLocation.fromNamespaceAndPath(id.getNamespace(), "models/item/" + id.getPath() + ".json");
            collectModelTextures(model, owner, new HashSet<>());
            collectArmorTextures(owner);
        } else {
            ResourceLocation state = ResourceLocation.fromNamespaceAndPath(id.getNamespace(), "blockstates/" + id.getPath() + ".json");
            JsonObject json = readJson(state);
            if (json == null) return;
            Set<ResourceLocation> models = new LinkedHashSet<>();
            findModelReferences(json, models, state);
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
                if (present(texture)) {
                    addTexture(texture, owner, "armor_filename_candidate", texture);
                }
            }
            return;
        }
    }

    private void collectModelTextures(ResourceLocation modelFile, Owner owner, Set<ResourceLocation> visiting) {
        if(visiting.size()>=64){omit("depth_limit",modelFile,"model traversal depth exceeds64");return;}
        if (visiting.contains(modelFile)) { omit("model_cycle", modelFile, "override traversal cycle"); return; }
        if (snapshotProcessed.contains(modelFile)) return;
        if (!visiting.add(modelFile)) { omit("model_cycle", modelFile, "override traversal cycle"); return; }
        try {
        ModelData data = readModel(modelFile, new HashSet<>());
        if (data == null) return;
        for (String value : data.textures().values()) {
            String resolved = resolveSnapshotAlias(value,data.textures());
            if (resolved == null) { omit("alias_unresolved", modelFile, "missing or cyclic texture alias"); continue; }
            try {
                ResourceLocation texture = ResourceLocation.parse(resolved);
                ResourceLocation png = ResourceLocation.fromNamespaceAndPath(texture.getNamespace(),
                        "textures/" + texture.getPath() + ".png");
                {
                    addTexture(png, owner, "model_texture_reference", modelFile);
                }
            } catch (RuntimeException ignored) { omit("invalid_reference", modelFile, "invalid texture reference"); }
        }
        for (ResourceLocation child : data.children()) collectModelTextures(modelPath(child), owner, visiting);
        } finally {
            { visiting.remove(modelFile); snapshotProcessed.add(modelFile); }
        }
    }

    private ModelData readModel(ResourceLocation file, Set<ResourceLocation> visiting) {
        if(file.getPath().startsWith("models/builtin/")) {
            if(!file.getPath().equals("models/builtin/generated.json")&&!file.getPath().equals("models/builtin/entity.json"))omit("builtin_unsupported",file,"unknown semantic builtin");
            return new ModelData(Map.of(),Set.of());
        }
        if(visiting.size()>=64){omit("depth_limit",file,"parent traversal depth exceeds64");return null;}
        ModelData cached = modelCache.get(file);
        if (cached != null) return cached;
        if (!visiting.add(file)) { omit("parent_cycle", file, "parent traversal cycle"); return null; }
        JsonObject json = readJson(file);
        if (json == null) { visiting.remove(file); return null; }
        Map<String, String> textures = new LinkedHashMap<>();
        Set<ResourceLocation> children = new LinkedHashSet<>();
        if (json.has("parent") && (!json.get("parent").isJsonPrimitive() || !json.getAsJsonPrimitive("parent").isString())) omit("invalid_parent", file, "parent must be a string");
        if (json.has("parent") && json.get("parent").isJsonPrimitive() && json.getAsJsonPrimitive("parent").isString()) {
            try {
                ModelData parent = readModel(modelPath(ResourceLocation.parse(json.get("parent").getAsString())), visiting);
                if (parent != null) textures.putAll(parent.textures());
            } catch (RuntimeException ignored) { omit("invalid_parent", file, "invalid model parent"); }
        }
        if (json.has("textures") && !json.get("textures").isJsonObject()) omit("invalid_reference", file, "textures must be an object");
        if (json.has("textures") && json.get("textures").isJsonObject()) {
            for (var entry : json.getAsJsonObject("textures").entrySet()) {
                if (entry.getValue().isJsonPrimitive() && entry.getValue().getAsJsonPrimitive().isString()) textures.put(entry.getKey(), entry.getValue().getAsString());
                else omit("invalid_reference", file, "texture value must be a string");
            }
        }
        if (json.has("overrides")) findModelReferences(json.get("overrides"), children, file);
        ModelData data = new ModelData(Map.copyOf(textures), Set.copyOf(children));
        modelCache.put(file, data);
        visiting.remove(file);
        return data;
    }

    private static String resolveSnapshotAlias(String value,Map<String,String> textures) {
        Set<String> visited=new HashSet<>();
        for(int depth=0;depth<64;depth++) {
            if(!value.startsWith("#"))return value;
            String key=value.substring(1);
            if(!visited.add(key))return null;
            value=textures.get(key);if(value==null)return null;
        }
        return value.startsWith("#")?null:value;
    }
    private JsonObject readJson(ResourceLocation file) {
        if (jsonCache.containsKey(file)) return jsonCache.get(file);
        JsonObject result = null;
        {
            try {
                if (++jsonReads > snapshotLimits.jsonReads()) throw new IOException("JSON read bound reached");
                var selected = ResourceSnapshot.external(snapshotAccess.stack(file));
                if (selected == null) throw new IOException("missing external JSON; renderer unsupported or unknown");
                long remaining = (long)snapshotLimits.jsonTotal()-jsonBytes;
                if (remaining <= 0) throw new IOException("JSON aggregate byte bound exhausted");
                int allowance = (int)Math.min(snapshotLimits.jsonEach(), remaining);
                byte[] bytes;
                try (var input = selected.open()) {
                    var consumed = new java.io.ByteArrayOutputStream();
                    byte[] buffer = new byte[Math.min(8192,allowance+1)];
                    while (consumed.size() <= allowance) {
                        int count = input.read(buffer,0,Math.min(buffer.length,allowance+1-consumed.size()));
                        if (count < 0) break;
                        jsonBytes += count; consumed.write(buffer,0,count);
                    }
                    bytes = consumed.toByteArray();
                }
                if (bytes.length > allowance) throw new IOException("JSON byte bound reached");
                sourceDocuments.put(file,new SourceDocument(file,selected.provider(),bytes));
                String text=new String(bytes,java.nio.charset.StandardCharsets.UTF_8);
                checkJsonDepth(text);
                JsonElement parsed = JsonParser.parseString(text);
                if (!parsed.isJsonObject()) throw new IOException("model JSON is not an object");
                result = parsed.getAsJsonObject();
            } catch (IOException | RuntimeException error) { omit("json_unresolved", file, error.toString()); }
            jsonCache.put(file, result);
            return result;
        }
    }

    private static void checkJsonDepth(String text) throws IOException {
        int depth=0;boolean string=false,escape=false;
        for(char c:text.toCharArray()) {
            if(string){if(escape)escape=false;else if(c=='\\')escape=true;else if(c=='"')string=false;}
            else if(c=='"')string=true;
            else if(c=='{'||c=='['){if(++depth>64)throw new IOException("JSON nesting exceeds64");}
            else if(c=='}'||c==']')depth--;
        }
    }
    private void findModelReferences(JsonElement element, Set<ResourceLocation> result, ResourceLocation file) {
        if (element.isJsonObject()) {
            for (var entry : element.getAsJsonObject().entrySet()) {
                if (entry.getKey().equals("model")) {
                    if (entry.getValue().isJsonPrimitive() && entry.getValue().getAsJsonPrimitive().isString()) {
                        try { result.add(ResourceLocation.parse(entry.getValue().getAsString())); }
                        catch (RuntimeException ignored) { omit("invalid_reference", file, "invalid model ID"); }
                    } else {
                        omit("invalid_reference", file, "model must be a string");
                    }
                } else findModelReferences(entry.getValue(), result, file);
            }
        } else if (element.isJsonArray()) {
            for (JsonElement child : element.getAsJsonArray()) findModelReferences(child, result, file);
        }
    }

    private static ResourceLocation modelPath(ResourceLocation model) {
        return ResourceLocation.fromNamespaceAndPath(model.getNamespace(), "models/" + model.getPath() + ".json");
    }
}
