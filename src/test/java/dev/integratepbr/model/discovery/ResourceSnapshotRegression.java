package dev.integratepbr.model.discovery;
import com.google.gson.*;
import net.minecraft.resources.ResourceLocation;
import java.io.*;
import java.nio.file.*;
import java.nio.charset.StandardCharsets;
import java.util.*;
import java.awt.image.BufferedImage;
import javax.imageio.ImageIO;

/** Uses production discovery/export with detached fixtures, without client bootstrap. */
public final class ResourceSnapshotRegression {
    static void check(boolean condition,String message){if(!condition)throw new AssertionError(message);}
    static ResourceLocation id(String value){return ResourceLocation.parse(value);}
    static ResourceSnapshot.Owner owner(String value,ResourceSnapshot.Kind kind){return new ResourceSnapshot.Owner(kind,id(value));}
    static byte[] png() throws IOException {
        BufferedImage image=new BufferedImage(11,5,BufferedImage.TYPE_INT_ARGB);
        for(int y=0;y<5;y++)for(int x=0;x<11;x++)image.setRGB(x,y,((x==4 && y>0 && y<4)?0:(x==2 && y==2?128:255))<<24 | ((x*17+3)<<16) | ((y*29+7)<<8) | 43);
        ByteArrayOutputStream output=new ByteArrayOutputStream();ImageIO.write(image,"png",output);return output.toByteArray();
    }
    static ResourceSnapshot.Entry entry(String pack,byte[] data){return new ResourceSnapshot.Entry(pack,()->new ByteArrayInputStream(data));}
    static void json(Map<ResourceLocation,List<ResourceSnapshot.Entry>> resources,String key,String json){resources.put(id(key),List.of(entry("fixture-json",json.getBytes(StandardCharsets.UTF_8))));}
    static void persisted(ResourceSnapshot.Captured capture,Path output,boolean missing) throws IOException {
        JsonObject stored=JsonParser.parseString(Files.readString(output.resolve("manifest.json"),StandardCharsets.UTF_8)).getAsJsonObject();
        check(stored.equals(capture.manifest()),"persisted semantic equality");
        JsonObject without=stored.deepCopy();String identity=without.remove("snapshot_id").getAsString();
        check(ResourceSnapshot.digest(ResourceSnapshot.canonical(without)).equals(identity),"persisted canonical identity");
        JsonObject texture=stored.getAsJsonArray("textures").get(0).getAsJsonObject();
        check(texture.has("sidecar")&&texture.get("sidecar").isJsonNull(),"explicit sidecar null");
        JsonObject companions=texture.getAsJsonObject("companions");
        check(companions.keySet().equals(Set.of("normal","specular"))&&companions.get("normal").isJsonNull()&&companions.get("specular").isJsonNull(),"explicit companion nulls");
        if(missing){for(String key:List.of("source","width","height"))check(texture.has(key)&&texture.get(key).isJsonNull(),"explicit missing "+key);
            check(!stored.getAsJsonObject("discovery").getAsJsonArray("omissions").isEmpty(),"missing-source omission");}
    }
    static boolean hasOmission(ResourceSnapshot.Captured capture,String kind) {
        for(var element:capture.manifest().getAsJsonObject("discovery").getAsJsonArray("omissions"))if(element.getAsJsonObject().get("kind").getAsString().equals(kind))return true;
        return false;
    }
    static ResourceSnapshot.Entry counting(String provider,byte[] bytes,int[] counters) {
        return new ResourceSnapshot.Entry(provider,()->{counters[0]++;return new ByteArrayInputStream(bytes){
            @Override public synchronized int read(byte[] buffer,int offset,int length){int n=super.read(buffer,offset,length);if(n>0)counters[1]+=n;return n;}
        };});
    }
    static void reviewedBoundaries(byte[] png) throws Exception {
        var selected=owner("fixture:dag",ResourceSnapshot.Kind.ITEM);
        var other=owner("other:dag",ResourceSnapshot.Kind.ITEM);
        Map<ResourceLocation,List<ResourceSnapshot.Entry>> map=new HashMap<>();
        String root="{\"overrides\":[{\"model\":\"fixture:a\"},{\"model\":\"fixture:b\"}]}";
        json(map,"fixture:models/item/dag.json",root);json(map,"other:models/item/dag.json",root);
        json(map,"fixture:models/a.json","{\"overrides\":[{\"model\":\"fixture:common\"}]}");
        json(map,"fixture:models/b.json","{\"overrides\":[{\"model\":\"fixture:common\"}]}");
        json(map,"fixture:models/common.json","{\"textures\":{\"base\":\"fixture:item/base\"}}");
        map.put(id("fixture:textures/item/base.png"),List.of(entry("png",png)));
        ResourceSnapshot.Access access=key->map.getOrDefault(key,List.of());
        var limits=ResourceSnapshot.Limits.defaults();
        var dag=ResourceSnapshot.capture(selected,List.of(selected,other),access,limits);
        check(!hasOmission(dag,"model_cycle"),"diamond is not cycle");
        check(dag.manifest().getAsJsonObject("discovery").get("shared_scope_complete").getAsBoolean(),"DAG complete candidate scope");
        check(dag.manifest().getAsJsonArray("textures").get(0).getAsJsonObject().getAsJsonArray("owners").size()==2,"DAG all owners");
        json(map,"fixture:models/common.json","{\"textures\":{\"base\":\"fixture:item/base\"},\"overrides\":[{\"model\":\"fixture:a\"}]}");
        check(hasOmission(ResourceSnapshot.capture(selected,List.of(selected),access,limits),"model_cycle"),"real override cycle");
        map.remove(id("fixture:models/common.json"));
        var missing=ResourceSnapshot.capture(selected,List.of(selected),access,limits);
        check(!hasOmission(missing,"model_cycle")&&hasOmission(missing,"json_unresolved"),"missing early return clears active path");
        String[] malformed={"{\"textures\":{\"ok\":\"fixture:item/base\"},\"overrides\":[{\"model\":17},{\"model\":\"BAD:bad\"}]}",
            "{\"textures\":{\"ok\":\"fixture:item/base\",\"bad\":true},\"parent\":false}",
            "{\"textures\":[],\"parent\":\"BAD:bad\",\"overrides\":[{\"model\":\"fixture:a\"}]}"};
        json(map,"fixture:models/common.json","{\"textures\":{\"base\":\"fixture:item/base\"}}");
        for(String model:malformed){json(map,"fixture:models/item/dag.json",model);var c=ResourceSnapshot.capture(selected,List.of(selected),access,limits);check(!c.manifest().getAsJsonObject("discovery").get("shared_scope_complete").getAsBoolean(),"malformed references incomplete");check(c.textureCount()>0,"valid coexisting references retained");}
        var block=owner("fixture:block",ResourceSnapshot.Kind.BLOCK);
        json(map,"fixture:blockstates/block.json","{\"variants\":{\"good\":{\"model\":\"fixture:common\"},\"bad\":{\"model\":true}}}");
        var blockCapture=ResourceSnapshot.capture(block,List.of(block),access,limits);check(blockCapture.textureCount()==1&&hasOmission(blockCapture,"invalid_reference"),"block-only invalid reference reported");
        var armor=owner("fixture:metal_helmet",ResourceSnapshot.Kind.ITEM);
        json(map,"fixture:models/item/metal_helmet.json","{}");map.put(id("fixture:textures/models/armor/metal_layer_1.png"),List.of(entry("armor",png)));
        check(ResourceSnapshot.capture(armor,List.of(armor),access,limits).manifest().getAsJsonArray("textures").get(0).getAsJsonObject().getAsJsonArray("evidence").get(0).getAsJsonObject().get("kind").getAsString().equals("armor_filename_candidate"),"armor remains candidate");
        int[] jsonCounts={0,0};byte[] oversized=new byte[50];Arrays.fill(oversized,(byte)'x');
        map.put(id("fixture:models/item/dag.json"),List.of(counting("json",oversized,jsonCounts)));
        map.put(id("other:models/item/dag.json"),List.of(new ResourceSnapshot.Entry("json",()->{throw new AssertionError("opened after JSON exhaustion");})));
        var bounded=ResourceSnapshot.capture(selected,List.of(selected,other),access,new ResourceSnapshot.Limits(10,10,100,10,10,1000,1000));
        check(jsonCounts[0]==1&&jsonCounts[1]==11&&hasOmission(bounded,"json_unresolved"),"actual JSON aggregate+sentinel bound");
        String exact="{\"textures\":{\"base\":\"fixture:item/base\"}}";
        json(map,"fixture:models/item/dag.json",exact);
        int[] assetCounts={0,0};map.put(id("fixture:textures/item/base.png"),List.of(counting("png",png,assetCounts)));
        map.put(id("fixture:textures/item/base.png.mcmeta"),List.of(new ResourceSnapshot.Entry("sidecar",()->{throw new AssertionError("opened after asset exhaustion");})));
        var assetBound=ResourceSnapshot.capture(selected,List.of(selected),access,new ResourceSnapshot.Limits(10,10,1000,1000,10,1000,10));
        check(assetCounts[0]==1&&assetCounts[1]==11&&hasOmission(assetBound,"asset_unresolved"),"actual asset aggregate+sentinel bound");
        map.remove(id("fixture:textures/item/base.png.mcmeta"));assetCounts[0]=0;assetCounts[1]=0;
        var exactCapture=ResourceSnapshot.capture(selected,List.of(selected),access,new ResourceSnapshot.Limits(10,10,1000,exact.getBytes(StandardCharsets.UTF_8).length,10,1000,png.length));
        check(exactCapture.textureCount()==1&&assetCounts[1]==png.length,"accepted exact aggregate budget preserved");
        // Repeated base references reuse detached inventory without opening a second stream.
        json(map,"fixture:models/item/dag.json","{\"textures\":{\"base\":\"fixture:item/base\",\"also\":\"fixture:item/base_n\"}}");
        int[] duplicate={0,0};map.put(id("fixture:textures/item/base_n.png"),List.of(counting("same",png,duplicate)));
        ResourceSnapshot.capture(selected,List.of(selected),access,limits);check(duplicate[0]==1&&duplicate[1]==png.length,"duplicate asset reuse");
        int[] repeated={0,0};byte[] common="{\"textures\":{\"base\":\"fixture:item/base\"}}".getBytes(StandardCharsets.UTF_8);
        map.put(id("fixture:models/common.json"),List.of(counting("json",common,repeated)));
        json(map,"fixture:models/item/dag.json",root);json(map,"other:models/item/dag.json",root);
        ResourceSnapshot.capture(selected,List.of(selected,other),access,limits);check(repeated[0]==1,"shared JSON one read");
        String terminal="{\"parent\":\"different:builtin/generated\",\"textures\":{\"layer0\":\"fixture:item/base\"}}";
        json(map,"fixture:models/item/dag.json",terminal);
        ResourceSnapshot.Access guarded=key->{if(key.getPath().startsWith("models/builtin/"))throw new AssertionError("builtin opened");return map.getOrDefault(key,List.of());};
        ResourceSnapshot.capture(selected,List.of(selected),guarded,limits);
        byte[] mutable=terminal.getBytes(StandardCharsets.UTF_8);map.put(id("fixture:models/item/dag.json"),List.of(entry("json",mutable)));
        var detached=ModelResourceIndex.snapshotScan(List.of(selected),access,limits);byte[] retained=detached.documents().get(0).bytes();mutable[0]='x';retained[0]='x';
        check(detached.documents().get(0).bytes()[0]=='{',"detached document arrays immutable");
        json(map,"fixture:models/item/dag.json","{\"nested\":"+"[".repeat(65)+"0"+"]".repeat(65)+"}");
        check(hasOmission(ResourceSnapshot.capture(selected,List.of(selected),access,limits),"json_unresolved"),"nesting limit");
        JsonObject aliases=new JsonObject();for(int n=0;n<70;n++)aliases.addProperty("a"+n,n==69?"fixture:item/base":"#a"+(n+1));
        JsonObject aliasModel=new JsonObject();aliasModel.add("textures",aliases);json(map,"fixture:models/item/dag.json",aliasModel.toString());
        check(hasOmission(ResourceSnapshot.capture(selected,List.of(selected),access,limits),"alias_unresolved"),"alias64 bound");
        for(boolean parent:List.of(true,false)) {
            for(int n=0;n<67;n++)json(map,"fixture:models/depth"+n+".json",n==66?"{}":parent?"{\"parent\":\"fixture:depth"+(n+1)+"\"}":"{\"overrides\":[{\"model\":\"fixture:depth"+(n+1)+"\"}]}");
            json(map,"fixture:models/item/dag.json","{\"parent\":\"fixture:depth0\"}");
            if(!parent)json(map,"fixture:models/item/dag.json","{\"overrides\":[{\"model\":\"fixture:depth0\"}]}");
            check(hasOmission(ResourceSnapshot.capture(selected,List.of(selected),access,limits),"depth_limit"),"model dependency depth64");
        }
    }
    public static void main(String[] args) throws Exception {
        Map<ResourceLocation,List<ResourceSnapshot.Entry>> resources=new HashMap<>();
        var selected=owner("registry_alias:sample",ResourceSnapshot.Kind.ITEM);
        json(resources,"registry_alias:models/item/sample.json","{\"parent\":\"fixture:parent\",\"textures\":{\"base\":\"minecraft:item/edge_n\",\"alias\":\"#base\"},\"overrides\":[{\"model\":\"fixture:override\",\"predicate\":{\"custom:state\":0.25}},{\"model\":\"fixture:shared_geometry\",\"predicate\":{\"custom:state\":0.5}}]}");
        json(resources,"fixture:models/parent.json","{\"textures\":{\"base\":\"minecraft:item/edge_n\",\"alias\":\"#base\"},\"elements\":[{\"from\":[1.5,2.25,3.5],\"to\":[12.5,14.25,9.5],\"faces\":{\"down\":{\"texture\":\"#alias\"},\"up\":{\"texture\":\"alias\"},\"north\":{\"texture\":\"#alias\",\"uv\":[15.5,13.25,-1,2.5],\"rotation\":90,\"tintindex\":2},\"south\":{\"texture\":\"#alias\"},\"west\":{\"texture\":\"#alias\"},\"east\":{\"texture\":\"#alias\"}}}]}");
        json(resources,"fixture:models/override.json","{\"parent\":\"fixture:parent\",\"textures\":{\"base\":\"minecraft:item/edge_n\"},\"elements\":[{\"from\":[0,1,2],\"to\":[7,4,5],\"faces\":{\"south\":{\"texture\":\"base\",\"tintindex\":0}}}]}");
        byte[] source=png();
        reviewedBoundaries(source);
        resources.put(id("minecraft:textures/item/edge_n.png"),List.of(entry("low",new byte[]{1}),entry("external_IntegratePBR_Generated_similar",source),entry(ResourceSnapshot.GENERATED_PACK,new byte[]{2})));
        ResourceSnapshot.Access access=key->resources.getOrDefault(key,List.of());
        var limits=ResourceSnapshot.Limits.defaults();
        var generatedOwner=owner("fixture:generated_test",ResourceSnapshot.Kind.ITEM);
        json(resources,"fixture:models/item/generated_test.json","{\"parent\":\"fixture:handheld\",\"textures\":{\"layer0\":\"minecraft:item/edge_n\"}}");
        json(resources,"fixture:models/handheld.json","{\"parent\":\"fixture:generated\"}");
        json(resources,"fixture:models/generated.json","{\"parent\":\"other:builtin/generated\"}");
        var blockOwner=owner("fixture:geometry_block",ResourceSnapshot.Kind.BLOCK);
        json(resources,"fixture:blockstates/geometry_block.json","{\"variants\":{\"facing=north\":[{\"model\":\"fixture:shared_geometry\",\"x\":90,\"y\":180,\"uvlock\":true,\"weight\":2},{\"model\":\"fixture:shared_geometry\",\"weight\":3}]},\"multipart\":[{\"when\":{\"OR\":[{\"powered\":\"true\"},{\"facing\":\"south\"}]},\"apply\":{\"model\":\"fixture:shared_geometry\",\"y\":270}}]}");
        json(resources,"fixture:models/shared_geometry.json","{\"textures\":{\"base\":\"minecraft:zz/geometry_shared\"},\"elements\":[{\"from\":[0,1,2],\"to\":[4,5,6],\"faces\":{\"up\":{\"texture\":\"base\"}}}]}");
        resources.put(id("minecraft:textures/zz/geometry_shared.png"),List.of(entry("shared-png",source)));
        var capture=ResourceSnapshot.capture(selected,List.of(selected,generatedOwner,blockOwner),access,limits);
        var manifest=capture.manifest();
        check(capture.textureCount()==2,"parent/alias/override + vanilla/suffix retention");
        check(manifest.getAsJsonObject("discovery").get("shared_scope_complete").getAsBoolean(),"resolved fixture scope");
        check(manifest.getAsJsonArray("textures").get(0).getAsJsonObject().getAsJsonObject("source").get("source_pack_id").getAsString().equals("external_IntegratePBR_Generated_similar"),"low to high/exact exclusion");
        check(capture.manifest().get("snapshot_id").equals(ResourceSnapshot.capture(selected,List.of(selected,generatedOwner,blockOwner),access,limits).manifest().get("snapshot_id")),"determinism");
        check(manifest.get("schema_version").getAsInt()==2,"v2 source inventory");
        check(manifest.getAsJsonArray("source_documents").size()==8,"all exact dependency documents captured");
        for(var document:manifest.getAsJsonArray("source_documents")) {
            var d=document.getAsJsonObject();check(d.get("source_pack_id").getAsString().equals("fixture-json"),"document provider");
            byte[] raw=resources.get(id(d.get("resource_id").getAsString())).get(0).open().readAllBytes();check(ResourceSnapshot.digest(raw).equals(d.get("sha256").getAsString()),"raw document hash");
        }
        for(String documentId:List.of("fixture:models/parent.json","registry_alias:models/item/sample.json")) {
            var original=resources.get(id(documentId));byte[] raw=original.get(0).open().readAllBytes();
            String text=new String(raw,StandardCharsets.UTF_8);
            for(String changed:List.of(text+" ",text.replace("0.25","0.375").replace("15.5","14.5"))) {
                if(changed.equals(text))continue;
                resources.put(id(documentId),List.of(entry("fixture-json",changed.getBytes(StandardCharsets.UTF_8))));
                check(!ResourceSnapshot.capture(selected,List.of(selected,generatedOwner,blockOwner),access,limits).manifest().get("snapshot_id").equals(manifest.get("snapshot_id")),"document-only identity");
            }
            resources.put(id(documentId),List.of(entry("changed-provider",raw)));
            check(!ResourceSnapshot.capture(selected,List.of(selected,generatedOwner,blockOwner),access,limits).manifest().get("snapshot_id").equals(manifest.get("snapshot_id")),"JSON provider identity");
            resources.put(id(documentId),original);
        }
        JsonObject golden=JsonParser.parseString("{\"a\":1,\"provider\":\"caf\u00e9\",\"context\":{\"renderer\":\"unknown\"}}").getAsJsonObject();
        System.out.println("golden="+ResourceSnapshot.digest(ResourceSnapshot.canonical(golden)));
        var temp=Files.createTempDirectory("snapshot-regression-");
        try {
            Path out=temp.resolve("snapshot");ResourceSnapshot.export(capture,out);persisted(capture,out,false);
            var originalBase=resources.remove(id("minecraft:textures/item/edge_n.png"));
            var missingCapture=ResourceSnapshot.capture(selected,List.of(selected),access,limits);
            Path missingOut=temp.resolve("missing");ResourceSnapshot.export(missingCapture,missingOut);persisted(missingCapture,missingOut,true);
            resources.put(id("minecraft:textures/item/edge_n.png"),originalBase);
            check(Arrays.equals(Files.readAllBytes(out.resolve("assets/minecraft/textures/item/edge_n.png")),source),"verbatim source");
            try{ResourceSnapshot.export(capture,out);throw new AssertionError("collision accepted");}catch(IOException expected){}
            try{ResourceSnapshot.export(capture,temp.resolve("failed"),(path,bytes)->{throw new IOException("injected");});throw new AssertionError("failure accepted");}catch(IOException expected){}
            check(!Files.exists(temp.resolve("failed")),"no failed output");
            source[0]^=1; check(capture.manifest().get("snapshot_id").equals(manifest.get("snapshot_id")),"detached mutation");source[0]^=1;
            resources.put(id("minecraft:textures/item/edge_n.png.mcmeta"),List.of(entry("sidecar-provider","{}".getBytes(StandardCharsets.UTF_8))));
            resources.put(id("minecraft:textures/item/edge_n_n.png"),List.of(entry("normal-provider",source)));
            var paired=ResourceSnapshot.capture(selected,List.of(selected),access,limits).manifest();
            check(!paired.get("snapshot_id").equals(manifest.get("snapshot_id")),"provider/context inventory identity");
            var pair=paired.getAsJsonArray("textures").get(0).getAsJsonObject();
            check(pair.getAsJsonObject("sidecar").get("source_pack_id").getAsString().equals("sidecar-provider"),"independent sidecar");
            check(pair.getAsJsonObject("companions").getAsJsonObject("normal").get("source_pack_id").getAsString().equals("normal-provider"),"independent companion");
            resources.remove(id("minecraft:textures/item/edge_n.png.mcmeta"));resources.remove(id("minecraft:textures/item/edge_n_n.png"));
            var block=owner("other:shared",ResourceSnapshot.Kind.BLOCK);
            json(resources,"other:blockstates/shared.json","{\"variants\":{\"\":{\"model\":\"fixture:parent\"}}}");
            check(ResourceSnapshot.capture(selected,List.of(selected,block),access,limits).manifest().getAsJsonArray("textures").get(0).getAsJsonObject().getAsJsonArray("owners").size()==2,"shared mixed owners");
            json(resources,"fixture:models/parent.json","{\"parent\":\"fixture:parent\",\"textures\":{\"base\":\"#base\"}}");
            check(!ResourceSnapshot.capture(selected,List.of(selected),access,limits).manifest().getAsJsonObject("discovery").get("shared_scope_complete").getAsBoolean(),"cycles unresolved");
            json(resources,"fixture:models/parent.json","bad json");check(!ResourceSnapshot.capture(selected,List.of(selected),access,limits).manifest().getAsJsonObject("discovery").get("shared_scope_complete").getAsBoolean(),"malformed unresolved");
            check(!ResourceSnapshot.capture(selected,List.of(selected),access,new ResourceSnapshot.Limits(1,1,8,8,1,4,4)).manifest().getAsJsonObject("discovery").get("shared_scope_complete").getAsBoolean(),"bounds recorded");
            AtlasSourceAttributionRegression.run(capture,ResourceSnapshot.capture(blockOwner,List.of(selected,generatedOwner,blockOwner),access,limits),args.length>0?Path.of(args[0]+"-atlas"):null);
            RuntimeModelObservationRegression.run(capture,ResourceSnapshot.capture(blockOwner,List.of(selected,generatedOwner,blockOwner),access,limits),args.length>0?Path.of(args[0]+"-runtime"):null);
            if(args.length>0)ResourceSnapshot.export(capture,Path.of(args[0]));
        } finally {try(var paths=Files.walk(temp)){for(Path path:paths.sorted(Comparator.reverseOrder()).toList())Files.delete(path);}}
        System.out.println("Resource snapshot regressions passed; renderer/UV unverified.");
    }
}
