package dev.integratepbr.model.discovery;

import com.google.gson.*;
import com.mojang.blaze3d.vertex.PoseStack;
import com.mojang.serialization.JsonOps;
import net.minecraft.client.Minecraft;
import net.minecraft.client.resources.model.BakedModel;
import net.minecraft.client.renderer.block.model.BakedQuad;
import net.minecraft.core.BlockPos;
import net.minecraft.core.Direction;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.util.RandomSource;
import net.minecraft.world.entity.HumanoidArm;
import net.minecraft.world.item.*;
import net.minecraft.world.level.block.RenderShape;
import net.neoforged.neoforge.client.ClientHooks;
import net.neoforged.neoforge.client.model.data.ModelData;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.*;

/** Selected API query only. No drawing, source mapping, or rendered-frame proof. */
public final class RuntimeModelObservation {
    public static ResourceSnapshot.Captured withHeldAtlasObservation(Minecraft mc, ResourceSnapshot.Captured source) {
        Bundle bundle = captureHeldBundle(mc);
        return ResourceSnapshot.withAtlasAttribution(ResourceSnapshot.withRuntimeObservation(source, bundle.bytes()), AtlasSourceAttribution.capture(mc, bundle));
    }
    public static ResourceSnapshot.Captured withBlockAtlasObservation(Minecraft mc, BlockPos pos, ResourceSnapshot.Captured source) {
        Bundle bundle = captureBlockBundle(mc, pos);
        return ResourceSnapshot.withAtlasAttribution(ResourceSnapshot.withRuntimeObservation(source, bundle.bytes()), AtlasSourceAttribution.capture(mc, bundle));
    }
    record Sprite(Object token,String id,String atlas,int width,int height,double u0,double u1,double v0,double v1) {}
    record Quad(int[] vertices,int packedCount,Sprite sprite,String facing,boolean shade,boolean ao,int tintIndex) {
        Quad(int[] input,Sprite sprite,String facing,boolean shade,boolean ao,int tintIndex){this(input,input==null?0:input.length,sprite,facing,shade,ao,tintIndex);}
        Quad {if(vertices!=null)vertices=vertices.length<=64?vertices.clone():null;}
        @Override public int[] vertices(){return vertices==null?null:vertices.clone();}
    }
    interface Query {
        JsonObject owner();JsonObject context();boolean item();
        Object base() throws Exception;Object resolved() throws Exception;Object transformed(Object resolved) throws Exception;
        boolean custom(Object model);boolean dispatchUnsupported();
        List<?> passes(Object model) throws Exception;List<?> types(Object pass) throws Exception;
        List<Quad> quads(Object model,Object type,String bucket,long seed) throws Exception;
        int tint(int index) throws Exception;
        default List<String> contextOmissions(){return List.of();}
    }
    static boolean resourceId(String value){if(value==null||!value.matches("[a-z0-9_.-]+:[a-z0-9_./-]+"))return false;for(String segment:value.substring(value.indexOf(':')+1).split("/",-1))if(segment.isEmpty()||segment.equals(".")||segment.equals(".."))return false;return true;}
    static boolean unicode(String value){for(int i=0;i<value.length();i++){char c=value.charAt(i);if(Character.isHighSurrogate(c)){if(++i>=value.length()||!Character.isLowSurrogate(value.charAt(i)))return false;}else if(Character.isLowSurrogate(c))return false;}return true;}
    static String safe(String value) {if(value==null)return null;if(!unicode(value))return "invalid_unicode";StringBuilder out=new StringBuilder();int bytes=0;for(int i=0;i<value.length();){int cp=value.codePointAt(i);String part=new String(Character.toChars(cp));int n=part.getBytes(StandardCharsets.UTF_8).length;if(bytes+n>512)break;out.append(part);bytes+=n;i+=Character.charCount(cp);}return out.toString();}
    static boolean safeTree(JsonElement value,int maxDepth,int maxNodes){record Node(JsonElement value,int depth){}ArrayDeque<Node> todo=new ArrayDeque<>();todo.add(new Node(value,0));int count=0;while(!todo.isEmpty()){Node n=todo.removeLast();if(++count>maxNodes||n.depth()>maxDepth)return false;JsonElement e=n.value();if(e==null||e.isJsonNull())continue;if(e.isJsonPrimitive()){JsonPrimitive q=e.getAsJsonPrimitive();if(q.isString()&&!unicode(q.getAsString())||q.isNumber()&&!Double.isFinite(q.getAsDouble()))return false;}else if(e.isJsonArray()){if(e.getAsJsonArray().size()>maxNodes-count-todo.size())return false;for(JsonElement child:e.getAsJsonArray())todo.add(new Node(child,n.depth()+1));}else{if(e.getAsJsonObject().size()>maxNodes-count-todo.size())return false;for(var entry:e.getAsJsonObject().entrySet()){if(!unicode(entry.getKey()))return false;todo.add(new Node(entry.getValue(),n.depth()+1));}}}return true;}
    static void failedEncoding(JsonObject item){for(String key:List.of("stack_encoding","stack_encoding_json","stack_encoding_sha256"))item.add(key,JsonNull.INSTANCE);item.addProperty("context_identity_complete",false);}
    static boolean encoding(JsonObject item,JsonElement encoding){failedEncoding(item);if(encoding==null||!encoding.isJsonObject()||!safeTree(encoding,32,100000))return false;String raw=new GsonBuilder().serializeNulls().disableHtmlEscaping().create().toJson(encoding);byte[] bytes=raw.getBytes(StandardCharsets.UTF_8);if(bytes.length>65536)return false;item.add("stack_encoding",encoding.deepCopy());item.addProperty("stack_encoding_json",raw);item.addProperty("stack_encoding_sha256",ResourceSnapshot.digest(bytes));item.addProperty("context_identity_complete",true);return true;}
    static <T extends Comparable<T>> String propertyValue(net.minecraft.world.level.block.state.properties.Property<T> property,Comparable<?> value){return property.getName(property.getValueClass().cast(value));}
    static JsonObject stateProperties(Map<net.minecraft.world.level.block.state.properties.Property<?>,Comparable<?>> values,List<String> omissions){JsonObject result=object();values.entrySet().stream().sorted(Comparator.comparing(e->e.getKey().getName())).forEach(e->{String key=e.getKey().getName(),value=propertyValue(e.getKey(),e.getValue());if(result.size()>=64||key.isEmpty()||value.isEmpty()||!unicode(key)||!unicode(value)||key.getBytes(StandardCharsets.UTF_8).length>256||value.getBytes(StandardCharsets.UTF_8).length>256){if(!omissions.contains("state_property_limit"))omissions.add("state_property_limit");}else result.addProperty(key,value);});return result;}
    static JsonArray array(double...values){JsonArray a=new JsonArray();for(double v:values){if(!Double.isFinite(v))throw new IllegalArgumentException("nonfinite numeric");a.add(v);}return a;}
    static JsonObject object(){return new JsonObject();}
    static void nullable(JsonObject o,String key,Object value){if(value==null)o.add(key,JsonNull.INSTANCE);else if(value instanceof Number n)o.addProperty(key,n);else if(value instanceof Boolean b)o.addProperty(key,b);else o.addProperty(key,value.toString());}
    record Bundle(byte[] bytes,Map<Integer,Object> spriteTokens){Bundle{bytes=bytes.clone();spriteTokens=Map.copyOf(spriteTokens);}@Override public byte[] bytes(){return bytes.clone();}}
    static byte[] fixture(Query query){return fixtureBundle(query).bytes();}
    static Bundle fixtureBundle(Query query){return captureBundle(query,"test_fixture");}
    private static Bundle captureBundle(Query query,String origin){Map<Integer,Object> tokens=new LinkedHashMap<>();byte[] bytes=capture(query,origin,tokens);JsonObject root=JsonParser.parseString(new String(bytes,StandardCharsets.UTF_8)).getAsJsonObject();if(root.getAsJsonArray("sprites").isEmpty())tokens.clear();return new Bundle(bytes,tokens);}
    private static byte[] capture(Query query,String origin,Map<Integer,Object> tokens) {
        JsonObject root=object();root.addProperty("schema_version",1);root.addProperty("origin",origin);root.addProperty("adapter","selected_baked_query_v1");root.add("selected_owner",query.owner().deepCopy());
        JsonObject context=query.context();root.add("context",context);
        JsonArray models=new JsonArray(),queries=new JsonArray(),sprites=new JsonArray(),quads=new JsonArray(),omissions=new JsonArray(),limitations=new JsonArray();
        root.add("models",models);root.add("queries",queries);root.add("sprites",sprites);root.add("quads",quads);root.add("omissions",omissions);root.add("limitations",limitations);
        limitations.add("source_mapping_unknown");limitations.add("selected_query_is_not_rendered_frame");limitations.add("mod_calls_cannot_be_preempted_by_count_limits");
        IdentityHashMap<Object,Integer> handles=new IdentityHashMap<>(),spriteHandles=new IdentityHashMap<>();
        boolean[] incomplete={false},unsupported={false};
        java.util.function.BiConsumer<String,String> omit=(code,detail)->{incomplete[0]=true;if(omissions.size()<256){JsonObject o=object();o.addProperty("code",code);o.addProperty("detail",safe(detail));omissions.add(o);}};
        java.util.function.Function<Object,Integer> handle=model->{if(model==null)return null;if(handles.containsKey(model))return handles.get(model);if(models.size()>=32){omit.accept("model_limit","model bound32");return null;}int index=models.size();handles.put(model,index);JsonObject m=object();m.addProperty("handle",index);m.addProperty("class_name",safe(model.getClass().getName()));m.add("resource_id",JsonNull.INSTANCE);models.add(m);return index;};
        JsonObject arm=context.getAsJsonObject(query.item()?"item":"block");
        for(String code:query.contextOmissions())omit.accept(code,"context data incomplete");
        if(!safeTree(context,32,100000)){if(query.item()){failedEncoding(arm);arm.add("pose_matrix",JsonNull.INSTANCE);}else arm.add("state_properties",object());omit.accept("context_structure_limit","unsafe context rejected");}
        if(!query.item()){JsonObject props=arm.getAsJsonObject("state_properties"),normalized=object();for(var entry:props.entrySet()){String key=entry.getKey();JsonElement val=entry.getValue();if(normalized.size()>=64||key.isEmpty()||!unicode(key)||key.getBytes(StandardCharsets.UTF_8).length>256||!val.isJsonPrimitive()||!val.getAsJsonPrimitive().isString()||val.getAsString().isEmpty()||!unicode(val.getAsString())||val.getAsString().getBytes(StandardCharsets.UTF_8).length>256){omit.accept("state_property_limit","unsafe/oversized property skipped");continue;}normalized.add(key,val);}arm.add("state_properties",normalized);}
        for(String key:List.of("dimension_id")){String value=context.get(key).getAsString();if(!resourceId(value)||!unicode(value)||value.getBytes(StandardCharsets.UTF_8).length>512){context.addProperty(key,"integratepbr:unknown");omit.accept("context_string_limit","context string unavailable");}}
        if(query.item()&&!arm.get("stack_encoding").isJsonNull()){JsonElement encoded=arm.get("stack_encoding");if(!safeTree(encoded,32,100000)||!unicode(arm.get("stack_encoding_json").getAsString())||arm.get("stack_encoding_json").getAsString().getBytes(StandardCharsets.UTF_8).length>65536){failedEncoding(arm);omit.accept("stack_encoding_failed","unsafe encoding");}}

        try {
            Object base=query.base();Integer bh=handle.apply(base);if(query.item())nullable(arm,"base_model_handle",bh);
            Object resolved=query.resolved();Integer rh=handle.apply(resolved);if(query.item())nullable(arm,"resolved_model_handle",rh);
            Object transformed=resolved==null?null:query.transformed(resolved);Integer th=handle.apply(transformed);
            if(query.item()){nullable(arm,"base_model_handle",bh);nullable(arm,"resolved_model_handle",rh);nullable(arm,"transformed_model_handle",th);}
            else nullable(arm,"model_handle",th);
            if(query.dispatchUnsupported()){unsupported[0]=true;limitations.add(query.item()?"unsupported_custom_or_trident_dispatch":"unsupported_block_render_shape");}
            else if(transformed==null){omit.accept("model_missing","selected model unavailable");}
            else if(query.dispatchUnsupported()||query.custom(transformed)){unsupported[0]=true;limitations.add(query.item()?"unsupported_custom_or_trident_dispatch":"unsupported_block_render_shape");}
            else {
                List<?> passes=query.passes(transformed);
                if(passes==null){omit.accept("null_passes","passes returned null");passes=List.of();}
                if(passes.size()>8)omit.accept("pass_limit","passes truncated8");
                for(int passIndex=0;passIndex<Math.min(8,passes.size());passIndex++) {
                    Object pass=passes.get(passIndex);Integer ph=handle.apply(pass);
                    if(pass==null||ph==null){omit.accept("null_pass","pass missing");continue;}
                    if(query.custom(pass)){unsupported[0]=true;limitations.add("custom_pass_unsupported");continue;}
                    List<?> types;
                    try{types=query.types(pass);}catch(Exception e){omit.accept("type_query_failed",e.toString());continue;}
                    if(types==null){omit.accept("null_types","types returned null");continue;}
                    if(types.size()>16)omit.accept("type_limit","types truncated16");
                    for(int typeIndex=0;typeIndex<Math.min(16,types.size());typeIndex++) {
                        Object type=types.get(typeIndex);if(type==null){omit.accept("null_render_type","type occurrence missing");continue;}
                        for(String bucket:Arrays.asList("down","up","north","south","west","east",null)) {
                            if(queries.size()>=896){omit.accept("query_limit","queries truncated896");break;}
                            long seed=query.item()?42:arm.get("state_seed").getAsLong();
                            JsonObject call=object();int qid=queries.size();call.addProperty("query_id",qid);call.addProperty("model_handle",ph);call.addProperty("pass_index",passIndex);call.addProperty("render_type_index",typeIndex);nullable(call,"render_type_class",type==null?null:safe(type.getClass().getName()));nullable(call,"render_type_diagnostic",type==null?null:safe(type.toString()));nullable(call,"bucket",bucket);call.addProperty("seed",seed);JsonArray indices=new JsonArray(),codes=new JsonArray();call.add("quad_indices",indices);call.add("omission_codes",codes);call.addProperty("status","complete");queries.add(call);
                            try {
                                List<Quad> returned=query.quads(pass,type,bucket,seed);
                                if(returned==null)throw new IllegalArgumentException("null quad collection");
                                if(returned.size()>128){codes.add("query_quad_limit");call.addProperty("status","incomplete");omit.accept("query_quad_limit","quads truncated128");}
                                for(int i=0;i<Math.min(128,returned.size());i++) {
                                    if(quads.size()>=2048){codes.add("quad_limit");call.addProperty("status","incomplete");omit.accept("quad_limit","total quads2048");break;}
                                    Quad quad=returned.get(i);if(quad==null||quad.facing()==null||!List.of("down","up","north","south","west","east").contains(quad.facing())){omit.accept("null_quad","quad missing");call.addProperty("status","incomplete");codes.add("null_quad");continue;}
                                    if(quad.vertices()==null&&quad.packedCount()<=64){omit.accept("missing_packed_vertices","malformed quad skipped");call.addProperty("status","incomplete");codes.add("missing_packed_vertices");continue;}
                                    JsonObject record=object();int id=quads.size();record.addProperty("quad_id",id);record.addProperty("query_id",qid);record.addProperty("facing",quad.facing());record.addProperty("shade",quad.shade());record.addProperty("ambient_occlusion",quad.ao());record.addProperty("tint_index",quad.tintIndex());JsonArray qc=new JsonArray();record.add("omission_codes",qc);record.addProperty("status","complete");
                                    Sprite sprite=quad.sprite();Integer sh=null;boolean spriteValid=false;
                                    if(sprite!=null&&sprite.token()!=null&&sprite.width()>0&&sprite.height()>0&&resourceId(sprite.id())&&resourceId(sprite.atlas())&&sprite.id().getBytes(StandardCharsets.UTF_8).length<=512&&sprite.atlas().getBytes(StandardCharsets.UTF_8).length<=512) {
                                        sh=spriteHandles.get(sprite.token());
                                        if(sh==null&&sprites.size()<256) {sh=sprites.size();spriteHandles.put(sprite.token(),sh);tokens.put(sh,sprite.token());JsonObject sp=object();sp.addProperty("sprite_handle",sh);sp.addProperty("sprite_id",sprite.id());sp.addProperty("atlas_id",sprite.atlas());sp.addProperty("width",sprite.width());sp.addProperty("height",sprite.height());
                                            for(String axis:List.of("u0","u1","v0","v1")){double value=switch(axis){case "u0"->sprite.u0();case "u1"->sprite.u1();case "v0"->sprite.v0();default->sprite.v1();};nullable(sp,axis,Double.isFinite(value)?value:null);}sp.addProperty("mapping_status","unknown");sprites.add(sp);}
                                        spriteValid=sh!=null&&Double.isFinite(sprite.u0())&&Double.isFinite(sprite.u1())&&Double.isFinite(sprite.v0())&&Double.isFinite(sprite.v1())&&sprite.u1()>sprite.u0()&&sprite.v1()>sprite.v0();
                                    }
                                    nullable(record,"sprite_handle",sh);
                                    int[] packed=quad.vertices();int count=quad.packedCount();record.addProperty("packed_vertex_count",count);JsonArray bits=new JsonArray();if(packed!=null)for(int value:packed)bits.add(value);record.add("packed_vertices",packed!=null?bits:JsonNull.INSTANCE);
                                    JsonArray decoded=new JsonArray(),local=new JsonArray();boolean valid=count==32&&packed!=null&&spriteValid;
                                    if(valid)for(int vertex=0;vertex<4;vertex++){int offset=vertex*8;double x=Float.intBitsToFloat(packed[offset]),y=Float.intBitsToFloat(packed[offset+1]),z=Float.intBitsToFloat(packed[offset+2]),u=Float.intBitsToFloat(packed[offset+4]),v=Float.intBitsToFloat(packed[offset+5]);if(!Double.isFinite(x)||!Double.isFinite(y)||!Double.isFinite(z)||!Double.isFinite(u)||!Double.isFinite(v)){valid=false;break;}JsonObject dv=object();dv.add("position",array(x,y,z));dv.add("atlas_uv",array(u,v));dv.addProperty("vertex_color",packed[offset+3]);decoded.add(dv);local.add(array((u-sprite.u0())/(sprite.u1()-sprite.u0()),(v-sprite.v0())/(sprite.v1()-sprite.v0())));}
                                    record.add("decoded_vertices",valid?decoded:JsonNull.INSTANCE);record.add("local_sprite_uv",valid?local:JsonNull.INSTANCE);
                                    if(count>64){qc.add("packed_storage_limit");omit.accept("packed_storage_limit","packed array not copied");}
                                    if(!valid){qc.add(count!=32?"packed_layout_unsupported":"sprite_or_vertex_invalid");record.addProperty("status","incomplete");omit.accept("quad_decode_incomplete","quad diagnostics retained");}
                                    JsonObject tint=object();tint.addProperty("encoding",query.item()?"item_argb32":"block_color_int");nullable(tint,"raw_color",null);nullable(tint,"error_code",null);tint.addProperty("status","untinted");
                                    if(quad.tintIndex()!=-1)try{tint.addProperty("raw_color",query.tint(quad.tintIndex()));tint.addProperty("status","sampled");}catch(Exception e){tint.addProperty("status","incomplete");tint.addProperty("error_code","tint_failed");qc.add("tint_failed");record.addProperty("status","incomplete");omit.accept("tint_failed",e.toString());}
                                    record.add("tint",tint);if(!record.get("status").getAsString().equals("complete")){call.addProperty("status","incomplete");codes.add("quad_incomplete");}quads.add(record);indices.add(id);
                                }
                            }catch(Exception e){call.addProperty("status","incomplete");codes.add("quad_query_failed");omit.accept("quad_query_failed",e.toString());}
                        }
                    }
                }
            }
        }catch(Exception e){omit.accept("model_query_failed",e.toString());}
        if(query.item()&&!arm.get("context_identity_complete").getAsBoolean())omit.accept("stack_encoding_failed","stack identity encoding incomplete");
        if(query.item()&&(arm.get("pose_matrix").isJsonNull()||arm.get("base_model_handle").isJsonNull()||arm.get("resolved_model_handle").isJsonNull()||arm.get("transformed_model_handle").isJsonNull())&&!unsupported[0])omit.accept("item_stage_incomplete","model/pose stage missing");
        if(!query.item()&&!unsupported[0]&&(arm.get("input_model_data_empty").isJsonNull()||arm.get("derived_model_data_empty").isJsonNull()))omit.accept("model_data_incomplete","data stage missing");
        root.addProperty("status",incomplete[0]?"incomplete":unsupported[0]?"unsupported":"complete");
        boolean structureSafe=safeTree(root,32,100000);byte[] bytes=structureSafe?encode(root):new byte[0];
        if(!structureSafe||bytes.length>4194304){for(String key:query.item()?List.of("base_model_handle","resolved_model_handle","transformed_model_handle"):List.of("model_handle"))arm.add(key,JsonNull.INSTANCE);root.add("models",new JsonArray());root.add("queries",new JsonArray());root.add("sprites",new JsonArray());root.add("quads",new JsonArray());if(query.item())failedEncoding(arm);JsonArray fallbackOmissions=new JsonArray();JsonObject omission=object();omission.addProperty("code",structureSafe?"observation_size_limit":"observation_structure_limit");omission.addProperty("detail","serialized observation exceeds4MiB");fallbackOmissions.add(omission);root.add("omissions",fallbackOmissions);root.addProperty("status","incomplete");bytes=encode(root);}
        return bytes;
    }
    static byte[] encode(JsonObject root){return new GsonBuilder().serializeNulls().disableHtmlEscaping().create().toJson(root).getBytes(StandardCharsets.UTF_8);}
    static Quad copy(BakedQuad q){var sp=q.getSprite();Sprite sprite=sp==null?null:new Sprite(sp,sp.contents().name().toString(),sp.atlasLocation().toString(),sp.contents().width(),sp.contents().height(),sp.getU0(),sp.getU1(),sp.getV0(),sp.getV1());return new Quad(q.getVertices(),sprite,q.getDirection().getName(),q.isShade(),q.hasAmbientOcclusion(),q.getTintIndex());}
    static JsonObject context(boolean item,String dimension,long time){JsonObject c=object();c.addProperty("selected_query_usage",item?"item":"block");c.addProperty("dimension_id",dimension);c.addProperty("game_time",time);c.addProperty("rendered_frame_verified",false);c.addProperty("visible_faces_evaluated",false);c.add("item",JsonNull.INSTANCE);c.add("block",JsonNull.INSTANCE);return c;}
    static byte[] captureHeld(Minecraft mc){return captureHeldBundle(mc).bytes();}
    static Bundle captureHeldBundle(Minecraft mc) {
        if(!mc.isSameThread()||mc.player==null||mc.level==null||mc.player.getMainHandItem().isEmpty())throw new IllegalStateException("held runtime query requires client thread/player/level/main-hand item");
        ItemStack stack=mc.player.getMainHandItem().copy();var level=mc.level;var player=mc.player;boolean left=player.getMainArm()==HumanoidArm.LEFT;ItemDisplayContext display=left?ItemDisplayContext.FIRST_PERSON_LEFT_HAND:ItemDisplayContext.FIRST_PERSON_RIGHT_HAND;int seed=player.getId()+display.ordinal();JsonObject owner=object();owner.addProperty("kind","item");owner.addProperty("id",BuiltInRegistries.ITEM.getKey(stack.getItem()).toString());JsonObject c=context(true,level.dimension().location().toString(),level.getGameTime()),item=object();item.addProperty("stack_count",stack.getCount());item.addProperty("entity_id",player.getId());item.addProperty("display_context",display.name());item.addProperty("left_hand",left);item.addProperty("model_seed",seed);item.addProperty("quad_seed",42);item.addProperty("pose_scope","camera_transform_then_item_center");for(String key:List.of("stack_encoding","stack_encoding_json","stack_encoding_sha256","base_model_handle","resolved_model_handle","transformed_model_handle","pose_matrix"))item.add(key,JsonNull.INSTANCE);item.addProperty("context_identity_complete",false);
        try{encoding(item,ItemStack.CODEC.encodeStart(level.registryAccess().createSerializationContext(JsonOps.INSTANCE),stack).getOrThrow());}catch(Exception ignored){failedEncoding(item);}
        c.add("item",item);PoseStack pose=new PoseStack();var renderer=mc.getItemRenderer();
        return captureBundle(new Query(){public JsonObject owner(){return owner;}public JsonObject context(){return c;}public boolean item(){return true;}public Object base(){return stack.is(Items.TRIDENT)?renderer.getItemModelShaper().getModelManager().getModel(net.minecraft.client.renderer.entity.ItemRenderer.TRIDENT_IN_HAND_MODEL):stack.is(Items.SPYGLASS)?renderer.getItemModelShaper().getModelManager().getModel(net.minecraft.client.renderer.entity.ItemRenderer.SPYGLASS_IN_HAND_MODEL):renderer.getItemModelShaper().getItemModel(stack);}public Object resolved(){var model=renderer.getModel(stack,level,player,seed);return model==mc.getModelManager().getMissingModel()?null:model;}public Object transformed(Object model){var result=ClientHooks.handleCameraTransforms(pose,(BakedModel)model,display,left);pose.translate(-0.5,-0.5,-0.5);float[] matrix=new float[16];pose.last().pose().get(matrix);double[] values=new double[16];for(int i=0;i<16;i++)values[i]=matrix[i];item.add("pose_matrix",array(values));c.add("item",item);return result;}public boolean custom(Object m){return ((BakedModel)m).isCustomRenderer();}public boolean dispatchUnsupported(){return stack.is(Items.TRIDENT);}public List<?> passes(Object m){return ((BakedModel)m).getRenderPasses(stack,true);}public List<?> types(Object m){return ((BakedModel)m).getRenderTypes(stack,true);}public List<Quad> quads(Object m,Object type,String side,long quadSeed){RandomSource random=RandomSource.create();random.setSeed(quadSeed);List<BakedQuad> result=((BakedModel)m).getQuads(null,side==null?null:Direction.byName(side),random);return bounded(result);}public int tint(int index){return mc.getItemColors().getColor(stack,index);}},"client_runtime_query");
    }
    private static List<Quad> bounded(List<BakedQuad> values){if(values==null)return null;List<Quad> result=new ArrayList<>();for(int i=0;i<Math.min(129,values.size());i++)try{result.add(values.get(i)==null?null:copy(values.get(i)));}catch(Exception e){result.add(null);}return result;}
    static byte[] captureBlock(Minecraft mc,BlockPos input){return captureBlockBundle(mc,input).bytes();}
    static Bundle captureBlockBundle(Minecraft mc,BlockPos input) {
        if(!mc.isSameThread()||mc.level==null||mc.player==null)throw new IllegalStateException("block runtime query requires client thread/player/level");
        BlockPos pos=input.immutable();var level=mc.level;var state=level.getBlockState(pos);JsonObject owner=object();owner.addProperty("kind","block");owner.addProperty("id",BuiltInRegistries.BLOCK.getKey(state.getBlock()).toString());JsonObject c=context(false,level.dimension().location().toString(),level.getGameTime()),block=object();JsonArray position=new JsonArray();position.add(pos.getX());position.add(pos.getY());position.add(pos.getZ());block.add("position",position);List<String> contextErrors=new ArrayList<>();block.add("state_properties",stateProperties(state.getValues(),contextErrors));block.addProperty("render_shape",state.getRenderShape().name());block.addProperty("state_seed",state.getSeed(pos));block.addProperty("model_data_origin","client_level_model_data_manager");for(String key:List.of("model_handle","input_model_data_empty","derived_model_data_empty"))block.add(key,JsonNull.INSTANCE);block.addProperty("chunk_mesh_reproduction",false);block.addProperty("block_entity_renderer_included",false);c.add("block",block);ModelData[] data={null};
        return captureBundle(new Query(){public List<String> contextOmissions(){return contextErrors;}public JsonObject owner(){return owner;}public JsonObject context(){return c;}public boolean item(){return false;}public Object base(){return null;}public Object resolved(){return state.getRenderShape()==RenderShape.MODEL?mc.getBlockRenderer().getBlockModel(state):null;}public Object transformed(Object model){ModelData inputData=level.getModelDataManager().getAt(pos);if(inputData==null)throw new IllegalArgumentException("model data missing");data[0]=((BakedModel)model).getModelData(level,pos,state,inputData);if(data[0]==null)throw new IllegalArgumentException("derived model data missing");block.addProperty("input_model_data_empty",inputData==ModelData.EMPTY);block.addProperty("derived_model_data_empty",data[0]==ModelData.EMPTY);return model;}public boolean custom(Object m){return false;}public boolean dispatchUnsupported(){return state.getRenderShape()!=RenderShape.MODEL;}public List<?> passes(Object m){return List.of(m);}public List<?> types(Object m){return ((BakedModel)m).getRenderTypes(state,RandomSource.create(state.getSeed(pos)),data[0]).asList();}public List<Quad> quads(Object m,Object type,String side,long seed){RandomSource random=RandomSource.create();random.setSeed(seed);return bounded(((BakedModel)m).getQuads(state,side==null?null:Direction.byName(side),random,data[0],(net.minecraft.client.renderer.RenderType)type));}public int tint(int index){return mc.getBlockColors().getColor(state,level,pos,index);}},"client_runtime_query");
    }
}
