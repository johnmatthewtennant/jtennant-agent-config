#import <Foundation/Foundation.h>
#import <objc/message.h>
#import <dlfcn.h>

static SEL S(NSString *name) { return NSSelectorFromString(name); }
static Class C(NSString *name) { return NSClassFromString(name); }
static id M0(id object, NSString *selector) {
    return ((id (*)(id, SEL))objc_msgSend)(object, S(selector));
}
static id M2(id object, NSString *selector, id first, id second) {
    return ((id (*)(id, SEL, id, id))objc_msgSend)(object, S(selector), first, second);
}
static void V1(id object, NSString *selector, id value) {
    ((void (*)(id, SEL, id))objc_msgSend)(object, S(selector), value);
}
static void VB(id object, NSString *selector, BOOL value) {
    ((void (*)(id, SEL, BOOL))objc_msgSend)(object, S(selector), value);
}

int main(int argc, const char **argv) {
    @autoreleasepool {
        dlopen("/System/Library/PrivateFrameworks/WorkflowKit.framework/WorkflowKit", RTLD_NOW | RTLD_GLOBAL);
        if (argc < 3) {
            fprintf(stderr, "usage: %s create|delete ID [NAME BODY_FILE TARGET_ENTITY_ID]\n", argv[0]);
            return 2;
        }

        NSString *command = @(argv[1]);
        NSString *identifier = @(argv[2]);
        NSError *error = nil;
        id database = ((id (*)(id, SEL, unsigned long, NSError **))objc_msgSend)(
            [C(@"WFDatabase") alloc], S(@"initWithPersistenceMode:error:"), 0UL, &error);
        if (!database) {
            NSLog(@"could not open Shortcuts database: %@", error);
            return 3;
        }

        if ([command isEqualToString:@"delete"]) {
            BOOL deleted = ((BOOL (*)(id, SEL, id, NSError **))objc_msgSend)(
                database, S(@"deleteWorkflowRecordWithIdentifier:error:"), identifier, &error);
            if (!deleted && error) {
                NSLog(@"could not delete temporary shortcut %@: %@", identifier, error);
                return 4;
            }
            return 0;
        }

        if (argc < 6) {
            fprintf(stderr, "create requires NAME BODY_FILE TARGET_ENTITY_ID\n");
            return 2;
        }
        NSString *name = @(argv[3]);
        NSString *body = [NSString stringWithContentsOfFile:@(argv[4])
                                                    encoding:NSUTF8StringEncoding
                                                       error:&error];
        if (!body) {
            NSLog(@"could not read body: %@", error);
            return 5;
        }
        NSString *targetEntityID = @(argv[5]);

        id options = [C(@"WFWorkflowCreationOptions") new];
        V1(options, @"setIdentifier:", identifier);
        id reference = ((id (*)(id, SEL, id, NSError **))objc_msgSend)(
            database, S(@"createWorkflowWithOptions:error:"), options, &error);
        if (!reference) {
            NSLog(@"could not create temporary shortcut reference: %@", error);
            return 6;
        }

        error = nil;
        id workflow = ((id (*)(id, SEL, id, id, NSError **))objc_msgSend)(
            C(@"WFWorkflow"), S(@"workflowWithReference:database:error:"), reference, database, &error);
        if (!workflow) {
            NSLog(@"could not load temporary shortcut: %@", error);
            return 7;
        }

        NSString *replyActionUUID = [[NSUUID UUID] UUIDString];
        NSDictionary *parameters = @{
            @"AppIntentDescriptor": @{
                @"AppIntentIdentifier": @"ReplyMessageIntent",
                @"BundleIdentifier": @"com.apple.mail",
                @"Name": @"Mail",
                @"TeamIdentifier": @"0000000000"
            },
            @"UUID": replyActionUUID,
            @"body": body,
            @"target": @{ @"identifier": targetEntityID }
        };

        id registry = M0(C(@"WFActionRegistry"), @"sharedRegistry");
        M0(registry, @"fill");
        NSDate *fillDeadline = [NSDate dateWithTimeIntervalSinceNow:15];
        while (((NSUInteger (*)(id, SEL))objc_msgSend)(registry, S(@"state")) < 2 &&
               fillDeadline.timeIntervalSinceNow > 0) {
            [[NSRunLoop currentRunLoop] runMode:NSDefaultRunLoopMode
                                     beforeDate:[NSDate dateWithTimeIntervalSinceNow:0.05]];
        }

        id action = M2(registry, @"createActionWithIdentifier:serializedParameters:",
                       @"com.apple.mail.ReplyMessageIntent", parameters);
        if (!action) {
            NSLog(@"could not serialize Mail ReplyMessageIntent");
            return 8;
        }
        NSDictionary *saveParameters = @{
            @"AppIntentDescriptor": @{
                @"AppIntentIdentifier": @"SaveDraftIntent",
                @"BundleIdentifier": @"com.apple.mail",
                @"Name": @"Mail",
                @"TeamIdentifier": @"0000000000"
            },
            @"UUID": [[NSUUID UUID] UUIDString],
            @"target": @{
                @"Value": @{
                    @"OutputUUID": replyActionUUID,
                    @"Type": @"ActionOutput",
                    @"OutputName": @"Reply Message"
                },
                @"WFSerializationType": @"WFTextTokenAttachment"
            }
        };
        id saveAction = M2(registry, @"createActionWithIdentifier:serializedParameters:",
                           @"com.apple.mail.SaveDraftIntent", saveParameters);
        if (!saveAction) {
            NSLog(@"could not serialize Mail SaveDraftIntent");
            return 10;
        }

        NSArray *workflowActions = @[action, saveAction];
        BOOL replyOnly = [NSProcessInfo.processInfo.environment[@"MAIL_REPLY_ONLY"] boolValue];
        if (replyOnly) {
            id nothingAction = M2(registry, @"createActionWithIdentifier:serializedParameters:",
                                  @"is.workflow.actions.nothing",
                                  @{ @"UUID": [[NSUUID UUID] UUIDString] });
            if (!nothingAction) {
                NSLog(@"could not serialize Nothing action");
                return 11;
            }
            workflowActions = @[action, nothingAction];
        }
        V1(workflow, @"setName:", name);
        VB(workflow, @"setUserProvidedName:", YES);
        V1(workflow, @"setActions:", workflowActions);
        VB(workflow, @"setHiddenFromLibraryAndSync:", NO);
        V1(workflow, @"setAssociatedAppBundleIdentifier:", @"com.apple.mail");

        __block BOOL done = NO;
        __block NSError *saveError = nil;
        void (^completion)(NSError *) = ^(NSError *value) {
            saveError = value;
            done = YES;
        };
        ((void (*)(id, SEL, id))objc_msgSend)(workflow, S(@"saveWithCompletionBlock:"), completion);
        NSDate *deadline = [NSDate dateWithTimeIntervalSinceNow:20];
        while (!done && deadline.timeIntervalSinceNow > 0) {
            [[NSRunLoop currentRunLoop] runMode:NSDefaultRunLoopMode
                                     beforeDate:[NSDate dateWithTimeIntervalSinceNow:0.05]];
        }
        if (!done || saveError) {
            NSLog(@"could not save temporary shortcut: %@", saveError);
            return 9;
        }
        return 0;
    }
}
