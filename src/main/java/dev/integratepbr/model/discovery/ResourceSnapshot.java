package dev.integratepbr.model.discovery;

import com.google.gson.*;
import net.minecraft.resources.ResourceLocation;
import net.minecraft.server.packs.resources.ResourceManager;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.security.MessageDigest;
import java.util.*;
import javax.imageio.ImageIO;

/** Explicit development capture. Unknown rendered geometry is never certified. */
public final class ResourceSnapshot {
    public enum Kind { ITEM, BLOCK }
    public record Owner(Kind kind, ResourceLocation id) {}
    public static final String GENERATED_PACK = "file/IntegratePBR_Generated";
    public record Limits(int owners, int jsonReads, int jsonEach, int jsonTotal, int textures, int assetEach, int assetTotal) {
        public static Limits defaults() { return new Limits(4096,8192,262144,8388608,128,4194304,16777216); }
    }
    @FunctionalInterface public interface Opener { InputStream open() throws IOException; }
    public record Entry(String provider, Opener opener) { public InputStream open() throws IOException { return opener.open(); } }
    @FunctionalInterface public interface Access { List<Entry> stack(ResourceLocation id) throws IOException; }
    public record Omission(String kind, ResourceSnapshot.Owner owner, ResourceLocation resource, String detail) {}
    public record Evidence(String kind, ResourceSnapshot.Owner owner, ResourceLocation resource) {}
    public static Entry external(List<Entry> stack) {
        for (int i=stack.size()-1;i>=0;i--) if (!GENERATED_PACK.equals(stack.get(i).provider())) return stack.get(i);
        return null;
    }
    public static Access access(ResourceManager manager) {
        return id -> manager.getResourceStack(id).stream().map(r -> new Entry(r.sourcePackId(), r::open)).toList();
    }
    public static final class Captured {
        private final JsonObject manifest;
        private final Map<String,byte[]> assets;
        private Captured(JsonObject manifest, Map<String,byte[]> assets) {
            this.manifest=manifest.deepCopy(); this.assets=new TreeMap<>();
            assets.forEach((k,v)->this.assets.put(k,v.clone()));
        }
        public JsonObject manifest() { return manifest.deepCopy(); }
        public int textureCount() { return manifest.getAsJsonArray("textures").size(); }
    }
    static JsonObject owner(ResourceSnapshot.Owner owner) {
        JsonObject o=new JsonObject(); o.addProperty("kind", owner.kind().name().toLowerCase(Locale.ROOT)); o.addProperty("id",owner.id().toString()); return o;
    }
    private static JsonObject omission(Omission item) {
        JsonObject o=new JsonObject();o.addProperty("kind",item.kind());o.add("owner",item.owner()==null?JsonNull.INSTANCE:owner(item.owner()));o.add("resource_id",item.resource()==null?JsonNull.INSTANCE:new JsonPrimitive(item.resource().toString()));o.addProperty("detail",item.detail());return o;
    }
    private static JsonArray sorted(Collection<JsonObject> objects) {
        TreeMap<String,JsonObject> unique=new TreeMap<>();
        for (JsonObject o:objects) unique.put(new String(canonical(o),StandardCharsets.UTF_8),o);
        JsonArray array=new JsonArray();unique.values().forEach(array::add);return array;
    }
    public static Captured capture(ResourceSnapshot.Owner selected, Iterable<ResourceSnapshot.Owner> owners, Access access, Limits limits) {
        var discovery=ModelResourceIndex.snapshotScan(owners,access,limits);
        List<Omission> omissions=new ArrayList<>(discovery.omissions());
        Map<String,byte[]> assets=new TreeMap<>(); long[] aggregate={0}; Map<String,JsonObject> capturedAssets=new HashMap<>();
        JsonArray textures=new JsonArray();
        var keys=discovery.textures().keySet().stream().filter(k->discovery.textures().get(k).contains(selected)).sorted(Comparator.comparing(Object::toString)).toList();
        for (ResourceLocation id:keys) {
            if(textures.size()>=limits.textures()) { omissions.add(new Omission("texture_limit",selected,id,"selected texture bound reached"));break; }
            JsonObject record=new JsonObject();record.addProperty("resource_id",id.toString());
            record.add("owners",sorted(discovery.textures().get(id).stream().map(ResourceSnapshot::owner).toList()));
            record.add("evidence",sorted(discovery.evidence().getOrDefault(id,List.of()).stream().map(e->{JsonObject o=new JsonObject();o.addProperty("kind",e.kind());o.add("owner",owner(e.owner()));o.addProperty("resource_id",e.resource().toString());return o;}).toList()));
            JsonElement base=captureAsset(id,access,limits,assets,capturedAssets,aggregate,omissions,selected);
            record.add("source",base);record.add("width",JsonNull.INSTANCE);record.add("height",JsonNull.INSTANCE);
            if(base.isJsonObject()) {
                try(var input=ImageIO.createImageInputStream(new ByteArrayInputStream(assets.get(base.getAsJsonObject().get("source_path").getAsString())))) {
                    var readers=ImageIO.getImageReaders(input);
                    if(!readers.hasNext()) throw new IOException("invalid PNG");
                    var reader=readers.next();
                    try { reader.setInput(input); int w=reader.getWidth(0),h=reader.getHeight(0);
                        if(!reader.getFormatName().equalsIgnoreCase("png") || w<=0 || h<=0 || w>4096 || h>4096 || (long)w*h>16777216) throw new IOException("PNG dimension bound or format");
                        record.addProperty("width",w);record.addProperty("height",h);
                    } finally { reader.dispose(); }
                } catch(IOException e) { omissions.add(new Omission("png_invalid",selected,id,e.toString()));record.add("source",JsonNull.INSTANCE); }
            }
            record.add("sidecar",captureAsset(ResourceLocation.fromNamespaceAndPath(id.getNamespace(),id.getPath()+".mcmeta"),access,limits,assets,capturedAssets,aggregate,omissions,null));
            JsonObject companions=new JsonObject();
            for(String role:List.of("normal","specular")) {
                String suffix=role.equals("normal")?"_n.png":"_s.png";
                var companion=ResourceLocation.fromNamespaceAndPath(id.getNamespace(),id.getPath().substring(0,id.getPath().length()-4)+suffix);
                companions.add(role,captureAsset(companion,access,limits,assets,capturedAssets,aggregate,omissions,null));
            }
            record.add("companions",companions);
            JsonObject context=new JsonObject();for(String field:List.of("renderer","render_surface","topology","orientation","tint")) context.addProperty(field,"unknown");
            JsonArray missing=new JsonArray();List.of("orientation","render_surface","renderer","tint","topology").forEach(missing::add);context.add("missing_fields",missing);record.add("context",context);textures.add(record);
        }
        JsonObject manifest=new JsonObject();manifest.addProperty("schema_version",2);manifest.add("selected_owner",owner(selected));
        JsonObject scope=new JsonObject();scope.addProperty("scope","registry_json_candidates_v1");scope.addProperty("shared_scope_complete",omissions.isEmpty());scope.addProperty("owner_count",discovery.ownerCount());scope.add("omissions",sorted(omissions.stream().map(ResourceSnapshot::omission).toList()));
        JsonArray documents=new JsonArray();
        for(var document:discovery.documents().stream().sorted(Comparator.comparing(d->d.id().toString())).toList()) {
            String path="assets/"+document.id().getNamespace()+"/"+document.id().getPath();safeRelative(path);
            byte[] bytes=document.bytes();assets.put(path,bytes.clone());
            JsonObject item=new JsonObject();item.addProperty("kind",document.id().getPath().startsWith("blockstates/")?"blockstate":"model");item.addProperty("resource_id",document.id().toString());item.addProperty("source_path",path);item.addProperty("source_pack_id",document.provider());item.addProperty("sha256",digest(bytes));item.addProperty("byte_count",bytes.length);documents.add(item);
        }
        manifest.add("source_documents",documents);
        manifest.add("discovery",scope);manifest.add("textures",textures);manifest.addProperty("snapshot_id",digest(canonical(manifest)));return new Captured(manifest,assets);
    }
    private static JsonElement captureAsset(ResourceLocation id, Access access, Limits limits, Map<String,byte[]> assets,Map<String,JsonObject> cache,long[] total,List<Omission> omissions,ResourceSnapshot.Owner required) {
        try {
            Entry entry=external(access.stack(id));
            if(entry==null) { if(required!=null) omissions.add(new Omission("missing_source",required,id,"no external source"));return JsonNull.INSTANCE; }
            String path="assets/"+id.getNamespace()+"/"+id.getPath();safeRelative(path);
            if(cache.containsKey(path)) {
                if(!cache.get(path).get("source_pack_id").getAsString().equals(entry.provider()))throw new IOException("inconsistent duplicate provider");
                return cache.get(path).deepCopy();
            }
            long remaining=(long)limits.assetTotal()-total[0];
            if(remaining<=0)throw new IOException("asset aggregate byte bound exhausted");
            int allowance=(int)Math.min(limits.assetEach(),remaining);
            byte[] bytes;
            try(var stream=entry.open()) {
                var consumed=new ByteArrayOutputStream();byte[] buffer=new byte[Math.min(8192,allowance+1)];
                while(consumed.size()<=allowance) {
                    int count=stream.read(buffer,0,Math.min(buffer.length,allowance+1-consumed.size()));
                    if(count<0)break;total[0]+=count;consumed.write(buffer,0,count);
                }
                bytes=consumed.toByteArray();
            }
            if(bytes.length>allowance)throw new IOException("asset byte bound reached");
            if(assets.containsKey(path) && !Arrays.equals(assets.get(path),bytes)) throw new IOException("inconsistent duplicate asset");

            assets.put(path,bytes.clone());JsonObject a=new JsonObject();a.addProperty("resource_id",id.toString());a.addProperty("source_path",path);a.addProperty("source_pack_id",entry.provider());a.addProperty("sha256",digest(bytes));a.addProperty("byte_count",bytes.length);cache.put(path,a.deepCopy());return a;
        } catch(IOException|RuntimeException error) {omissions.add(new Omission("asset_unresolved",required,id,error.toString()));return JsonNull.INSTANCE;}
    }
    static void safeRelative(String path) {
        if(path.contains("\\")||path.contains(":")||Arrays.stream(path.split("/",-1)).anyMatch(p->p.isEmpty()||p.equals(".")||p.equals("..")))throw new IllegalArgumentException("unsafe path");
    }
    public static String digest(byte[] bytes) {
        try {return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(bytes));}catch(Exception e){throw new IllegalStateException(e);}
    }
    public static byte[] canonical(JsonElement value) {
        ByteArrayOutputStream out=new ByteArrayOutputStream();canonicalInto(value,out);return out.toByteArray();
    }
    private static void ascii(ByteArrayOutputStream out,String text) {out.writeBytes(text.getBytes(StandardCharsets.UTF_8));}
    private static void canonicalInto(JsonElement value,ByteArrayOutputStream out) {
        if(value.isJsonNull()){ascii(out,"N");return;}
        if(value.isJsonArray()){ascii(out,"A"+value.getAsJsonArray().size()+":");value.getAsJsonArray().forEach(v->canonicalInto(v,out));return;}
        if(value.isJsonObject()){var object=value.getAsJsonObject();ascii(out,"O"+object.size()+":");new TreeSet<>(object.keySet()).forEach(k->{canonicalInto(new JsonPrimitive(k),out);canonicalInto(object.get(k),out);});return;}
        var primitive=value.getAsJsonPrimitive();
        if(primitive.isBoolean()){ascii(out,primitive.getAsBoolean()?"T":"F");return;}
        if(primitive.isNumber()){String number=primitive.getAsString();if(!number.matches("-?[0-9]+"))throw new IllegalArgumentException("integer required");ascii(out,"I"+number+";");return;}
        String string=primitive.getAsString();
        for(int i=0;i<string.length();i++){char c=string.charAt(i);if(Character.isHighSurrogate(c)){if(i+1>=string.length()||!Character.isLowSurrogate(string.charAt(++i)))throw new IllegalArgumentException("unpaired surrogate");}else if(Character.isLowSurrogate(c))throw new IllegalArgumentException("unpaired surrogate");}
        byte[] bytes=string.getBytes(StandardCharsets.UTF_8);ascii(out,"S"+bytes.length+":");out.writeBytes(bytes);
    }
    public static Captured withRuntimeObservation(Captured source,byte[] observation) {
        if(observation.length>4194304)throw new IllegalArgumentException("observation byte bound");
        JsonObject parsed=JsonParser.parseString(new String(observation,StandardCharsets.UTF_8)).getAsJsonObject();
        if(!parsed.getAsJsonObject("selected_owner").equals(source.manifest.getAsJsonObject("selected_owner")))throw new IllegalArgumentException("runtime selected owner mismatch");
        JsonObject manifest=source.manifest.deepCopy();manifest.remove("snapshot_id");manifest.addProperty("schema_version",3);
        JsonObject descriptor=new JsonObject();descriptor.addProperty("observation_schema_version",1);descriptor.addProperty("source_path","observations/runtime.json");descriptor.addProperty("sha256",digest(observation));descriptor.addProperty("byte_count",observation.length);manifest.add("runtime_observation",descriptor);manifest.addProperty("snapshot_id",digest(canonical(manifest)));
        Map<String,byte[]> assets=new TreeMap<>();source.assets.forEach((k,v)->assets.put(k,v.clone()));assets.put("observations/runtime.json",observation.clone());return new Captured(manifest,assets);
    }
    public static Captured withAtlasAttribution(Captured source,AtlasSourceAttribution.Captured attribution){
        if(source.manifest.get("schema_version").getAsInt()!=3)throw new IllegalArgumentException("atlas attachment requires v3");byte[] bytes=attribution.bytes();if(bytes.length>8388608)throw new IllegalArgumentException("attribution byte bound");JsonObject parsed=JsonParser.parseString(new String(bytes,StandardCharsets.UTF_8)).getAsJsonObject();if(!parsed.getAsJsonObject("selected_owner").equals(source.manifest.getAsJsonObject("selected_owner"))||!parsed.get("runtime_sha256").getAsString().equals(source.manifest.getAsJsonObject("runtime_observation").get("sha256").getAsString()))throw new IllegalArgumentException("atlas runtime linkage");
        Map<String,byte[]> assets=new TreeMap<>();source.assets.forEach((k,v)->assets.put(k,v.clone()));for(var e:attribution.assets().entrySet()){String path=e.getKey();if(!path.startsWith("evidence/atlas/")||path.contains("\\")||path.contains(":")||Arrays.stream(path.split("/",-1)).anyMatch(p->p.isEmpty()||p.equals(".")||p.equals(".."))||assets.containsKey(path))throw new IllegalArgumentException("atlas asset path collision");assets.put(path,e.getValue().clone());}assets.put("observations/atlas-attribution.json",bytes.clone());JsonObject manifest=source.manifest.deepCopy();manifest.remove("snapshot_id");manifest.addProperty("schema_version",4);JsonObject descriptor=new JsonObject();descriptor.addProperty("attribution_schema_version",1);descriptor.addProperty("source_path","observations/atlas-attribution.json");descriptor.addProperty("sha256",digest(bytes));descriptor.addProperty("byte_count",bytes.length);manifest.add("atlas_attribution",descriptor);manifest.addProperty("snapshot_id",digest(canonical(manifest)));return new Captured(manifest,assets);
    }
    @FunctionalInterface interface Writer { void write(Path path,byte[] bytes) throws IOException; }
    public static void export(Captured capture,Path destination) throws IOException {export(capture,destination,Files::write);}
    static void export(Captured capture,Path destination,Writer writer) throws IOException {
        Path absolute=destination.toAbsolutePath().normalize();
        for(Path part:absolute)if(part.toString().equalsIgnoreCase("resourcepacks"))throw new IOException("development export outside resourcepacks required");
        if(Files.exists(absolute,LinkOption.NOFOLLOW_LINKS))throw new IOException("snapshot destination exists");
        Files.createDirectories(absolute.getParent());
        if(!absolute.getParent().toRealPath().equals(absolute.getParent()))throw new IOException("symlink export parent");
        Path stage=Files.createTempDirectory(absolute.getParent(),".integratepbr-snapshot-");
        try {
            for(var asset:capture.assets.entrySet()){Path path=stage.resolve(asset.getKey()).normalize();if(!path.startsWith(stage))throw new IOException("asset escape");Files.createDirectories(path.getParent());writer.write(path,asset.getValue().clone());if(!Arrays.equals(Files.readAllBytes(path),asset.getValue()))throw new IOException("persisted asset changed");}
            byte[] manifestBytes=new GsonBuilder().serializeNulls().setPrettyPrinting().disableHtmlEscaping().create().toJson(capture.manifest).getBytes(StandardCharsets.UTF_8);
            if(manifestBytes.length>8388608)throw new IOException("v2 manifest byte bound");
            writer.write(stage.resolve("manifest.json"),manifestBytes);
            Files.move(stage,absolute);
        } finally {if(Files.exists(stage))try(var paths=Files.walk(stage)){for(Path path:paths.sorted(Comparator.reverseOrder()).toList())Files.delete(path);}}
    }
}
